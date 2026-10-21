import pytest

from subwatch.extract.merchants import MerchantBook, clean_descriptor, guess_name_from_sender, normalize_descriptor


@pytest.fixture(scope="module")
def book():
    return MerchantBook.load()


@pytest.mark.parametrize("raw,name", [
    ("NETFLIX.COM*123", "Netflix"),
    ("NETFLIX.COM      LOS GATOS   CA", "Netflix"),
    ("SPOTIFY P1A2B3C4D5 STOCKHOLM", "Spotify"),
    ("GOOGLE *YouTubePremium g.co/helppay#", "YouTube Premium"),
    ("GOOGLE *Google One", "Google One"),
    ("APPLE.COM/BILL ITUNES.COM", "Apple"),
    ("YANDEX*PLUS MOSCOW", "Яндекс Плюс"),
    ("Яндекс Плюс", "Яндекс Плюс"),
    ("PAYPAL *DROPBOX 4029357733", "Dropbox"),
    ("OPENAI *CHATGPT SUBSCR", "ChatGPT Plus"),
    ("JETBRAINS S.R.O. PRAHA", "JetBrains"),
    ("MSFT *XBOX GAME PASS", "Xbox Game Pass"),
    ("KINOPOISK HD", "Кинопоиск"),
    ("Beeline KZ Almaty", "Beeline"),
])
def test_normalize_known(book, raw, name):
    assert normalize_descriptor(raw, book)[0] == name


@pytest.mark.parametrize("raw,clean", [
    ("ACME CLOUD*99812", "Acme Cloud"),
    ("SQ *COFFEE LAB #3321", "Coffee Lab"),
    ("WWW.FOOBAR.IO", "Foobar"),
    ("PP*TASKLANE 77412", "Tasklane"),
])
def test_clean_unknown(raw, clean):
    assert clean_descriptor(raw) == clean


def test_user_dictionary_extends_and_overrides(tmp_path):
    user = tmp_path / "merchants.toml"
    user.write_text(
        '[netflix]\ncategory = "other"\n\n'
        '[megadisk]\nname = "Мегадиск"\ncategory = "cloud"\nsenders = ["megadisk.example"]\n'
        'patterns = [\'megadisk\']\nperiod = "1m"\n',
        encoding="utf-8",
    )
    b = MerchantBook.load(user)
    assert b.find_service("Netflix").category == "other"
    assert normalize_descriptor("MEGADISK*42", b)[0] == "Мегадиск"
    m = b.match_message("billing@megadisk.example", "Чек", "")
    assert m and m.merchant.name == "Мегадиск"


def test_shared_sender_needs_pattern(book):
    # apple.com sends receipts for many services; the text decides which.
    assert book.match_message("no_reply@email.apple.com", "Ваш чек", "Apple Music, ежемесячно").merchant.name == "Apple Music"
    assert book.match_message("no_reply@email.apple.com", "Ваш чек", "iCloud+ 50 ГБ").merchant.name == "iCloud+"
    # Without a hint we fall back to the umbrella entry.
    assert book.match_message("no_reply@email.apple.com", "Ваш чек", "Спасибо").merchant.name == "Apple"


def test_specific_beats_generic(book):
    m = book.match_message("billing@github.com", "Payment receipt for GitHub Copilot", "")
    assert m.merchant.name == "GitHub Copilot"


def test_bundles(book):
    partners = book.bundle_partners("Яндекс Плюс")
    assert "кинопоиск" in partners


def test_guess_name_from_sender():
    assert guess_name_from_sender("Tasklane Billing", "billing@tasklane.io") == "Tasklane"
    assert guess_name_from_sender("", "noreply@mail.acme-cloud.io") == "Acme-cloud"
