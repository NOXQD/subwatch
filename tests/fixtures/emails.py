"""Synthetic emails in Russian, English and Kazakh with the expected result.

expect=None means "not a subscription": no detection, or one below the
review threshold. status is what the default thresholds should give:
"active" (auto-accepted), "review" (queue) or "ignored".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid


@dataclass
class Expect:
    service: str
    kind: str = "charge"
    amount: str | None = None
    currency: str | None = None
    period: str | None = None
    next: str | None = None
    trial_until: str | None = None
    old_amount: str | None = None
    status: str = "active"
    category: str | None = None


@dataclass
class Email:
    id: str
    lang: str
    sender: str
    sender_name: str
    subject: str
    date: str
    text: str = ""
    html: str = ""
    expect: Expect | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        msg = EmailMessage()
        msg["From"] = f"{self.sender_name} <{self.sender}>"
        msg["To"] = "user@example.org"
        msg["Subject"] = self.subject
        msg["Date"] = format_datetime(datetime.fromisoformat(self.date))
        msg["Message-ID"] = make_msgid(idstring=self.id, domain="test.local")
        for k, v in self.headers.items():
            msg[k] = v
        if self.html and self.text:
            msg.set_content(self.text)
            msg.add_alternative(self.html, subtype="html")
        elif self.html:
            msg.set_content(self.html, subtype="html")
        else:
            msg.set_content(self.text)
        return msg.as_bytes()


EMAILS: list[Email] = [
    # ----------------------------------------------------------------- ru
    Email(
        "ru_netflix_receipt", "ru", "info@account.netflix.com", "Netflix",
        "Ваш платёж прошёл успешно", "2026-10-01T09:15:00+05:00",
        text="Здравствуйте, Иван!\nСпасибо за оплату подписки Netflix.\nТариф: Стандартный\n"
             "Сумма: 3 990,00 ₸\nСледующее списание: 1 ноября 2026\n"
             "Карта VISA •••• 4417",
        expect=Expect("Netflix", amount="3990.00", currency="KZT", period="1m", next="2026-11-01",
                      category="video"),
    ),
    Email(
        "ru_yandex_plus_renewal", "ru", "noreply@plus.yandex.ru", "Яндекс Плюс",
        "Подписка Яндекс Плюс продлена", "2026-10-15T08:00:00+03:00",
        text="Здравствуйте!\nВаша подписка Плюс Мульти продлена на месяц.\nСписано: 399 ₽\n"
             "Следующее списание — 15 ноября 2026 года.\nУправлять подпиской: https://plus.yandex.ru/my",
        expect=Expect("Яндекс Плюс", amount="399", currency="RUB", period="1m", next="2026-11-15"),
    ),
    Email(
        "ru_kinopoisk_trial", "ru", "hello@kinopoisk.ru", "Кинопоиск",
        "Пробный период Кинопоиска начался", "2026-10-22T10:00:00+03:00",
        text="Вы подключили пробный период на 30 дней.\n"
             "Пробный период закончится 21 ноября 2026, после этого спишем 299 ₽ в месяц.",
        expect=Expect("Кинопоиск", kind="trial", amount="299", currency="RUB", period="1m",
                      trial_until="2026-11-21"),
    ),
    Email(
        "ru_ivi_price_change", "ru", "info@ivi.ru", "Иви",
        "Изменение стоимости подписки Иви", "2026-10-20T12:00:00+03:00",
        text="С 1 декабря 2026 года стоимость подписки изменится: вместо 399 ₽ новая цена "
             "составит 499 ₽ в месяц.",
        expect=Expect("Иви", kind="price_change", amount="499", currency="RUB", period="1m",
                      next="2026-12-01", old_amount="399"),
    ),
    Email(
        "ru_okko_cancel", "ru", "noreply@okko.tv", "Okko",
        "Подписка отменена", "2026-10-18T19:30:00+03:00",
        text="Вы отменили подписку «Оптимальный». Подписка не будет продлена и закончится "
             "30 октября 2026.",
        expect=Expect("Okko", kind="cancellation"),
    ),
    Email(
        "ru_vk_music_receipt", "ru", "admin@vk.com", "ВКонтакте",
        "Чек об оплате VK Музыки", "2026-10-03T14:00:00+03:00",
        html="<html><body><p>Оплата подписки <b>VK Музыка</b></p>"
             "<table><tr><td>Сумма</td><td>199 ₽</td></tr>"
             "<tr><td>Период</td><td>1 месяц</td></tr></table>"
             "<p>Следующий платёж: 03.11.2026</p><p style='color:#999'>ООО «В Контакте»</p>"
             "</body></html>",
        expect=Expect("VK Музыка", amount="199", currency="RUB", period="1m", next="2026-11-03",
                      category="music"),
    ),
    Email(
        "ru_skillbox_monthly", "ru", "info@skillbox.ru", "Skillbox",
        "Ежемесячный платёж по подписке", "2026-10-12T09:00:00+03:00",
        text="Списано 4 990 ₽ за доступ к курсам на месяц.\nСледующее списание 12.11.2026.",
        expect=Expect("Skillbox", amount="4990", currency="RUB", period="1m", next="2026-11-12",
                      category="education"),
    ),
    Email(
        "ru_icloud_receipt", "ru", "no_reply@email.apple.com", "Apple",
        "Ваш чек от Apple", "2026-10-05T07:12:00+05:00",
        text="iCloud+ с 200 ГБ хранилища (ежемесячно)\nПродлевается 5 ноября 2026 г.\n"
             "Итого: 1 490 ₸",
        expect=Expect("iCloud+", amount="1490", currency="KZT", period="1m", next="2026-11-05",
                      category="cloud"),
    ),
    Email(
        "ru_ozon_order", "ru", "noreply@ozon.ru", "Ozon",
        "Ваш заказ №73829-0011 оплачен", "2026-10-10T11:00:00+03:00",
        text="Спасибо за оплату! Заказ №73829-0011 на сумму 12 450 ₽ будет доставлен 25 октября.",
        expect=None,
    ),
    Email(
        "ru_yandex_id_code", "ru", "noreply@id.yandex.ru", "Яндекс ID",
        "Код подтверждения", "2026-10-11T22:00:00+03:00",
        text="Ваш код подтверждения: 482913. Никому его не сообщайте.",
        expect=None,
    ),
    Email(
        "ru_kinopoisk_newsletter", "ru", "news@kinopoisk.ru", "Кинопоиск",
        "Новинки недели: 10 фильмов на выходные", "2026-10-16T18:00:00+03:00",
        text="Смотрите новые фильмы по подписке. Если не хотите получать письма — отписаться от рассылки.",
        headers={"List-Unsubscribe": "<mailto:unsub@kinopoisk.ru>"},
        expect=None,
    ),
    Email(
        "ru_megafon_monthly", "ru", "info@megafon.ru", "МегаФон",
        "Абонентская плата за ноябрь", "2026-10-31T06:00:00+03:00",
        text="Списана абонентская плата по тарифу «Без переплат»: 650 ₽.\n"
             "Следующее списание 1 декабря 2026.",
        expect=Expect("МегаФон", amount="650", currency="RUB", period="1m", next="2026-12-01"),
    ),
    Email(
        "ru_megadisk_unknown", "ru", "billing@megadisk.example", "Мегадиск",
        "Продление подписки", "2026-10-07T10:00:00+03:00",
        text="Ваша подписка на тариф «Про» продлена. Сумма: 590 ₽ в месяц.",
        expect=Expect("Мегадиск", amount="590", currency="RUB", period="1m", status="review"),
    ),
    # ----------------------------------------------------------------- en
    Email(
        "en_spotify_receipt", "en", "no-reply@spotify.com", "Spotify",
        "Your Spotify Premium receipt", "2026-10-14T16:20:00+00:00",
        text="Thanks for your payment.\nPremium Individual — $11.99/month\n"
             "Your next payment is on November 14, 2026.\nOrder ID: 9876543210",
        expect=Expect("Spotify", amount="11.99", currency="USD", period="1m", next="2026-11-14",
                      category="music"),
    ),
    Email(
        "en_github_copilot", "en", "billing@github.com", "GitHub",
        "[GitHub] Payment receipt for GitHub Copilot", "2026-10-07T03:00:00+00:00",
        text="We received payment for your GitHub Copilot Pro subscription.\nAmount: $10.00 USD\n"
             "Billing period: Oct 7, 2026 – Nov 6, 2026\nYour next billing date is November 7, 2026.",
        expect=Expect("GitHub Copilot", amount="10.00", currency="USD", period="1m", next="2026-11-07",
                      category="software"),
    ),
    Email(
        "en_chatgpt_plus", "en", "noreply@tm.openai.com", "OpenAI",
        "Your ChatGPT Plus subscription has been renewed", "2026-10-02T12:00:00+00:00",
        text="Your ChatGPT Plus subscription renewed successfully.\nTotal charged: $20.00\n"
             "Next renewal: November 2, 2026",
        expect=Expect("ChatGPT Plus", amount="20.00", currency="USD", period="1m", next="2026-11-02"),
    ),
    Email(
        "en_netflix_price_increase", "en", "info@mailer.netflix.com", "Netflix",
        "An update on your Netflix membership price", "2026-10-19T10:00:00+00:00",
        text="We're writing to let you know that the price of your Standard plan is changing. "
             "Your new price will be $17.99/month, up from $15.49, starting with your billing date "
             "on December 5, 2026.",
        expect=Expect("Netflix", kind="price_change", amount="17.99", currency="USD", period="1m",
                      next="2026-12-05", old_amount="15.49"),
    ),
    Email(
        "en_dropbox_annual", "en", "no-reply@dropbox.com", "Dropbox",
        "Your Dropbox Plus plan has renewed", "2026-10-18T08:00:00+00:00",
        text="Thanks for staying with Dropbox Plus.\nAnnual plan: $119.88 billed yearly\n"
             "Renews on October 18, 2027.",
        expect=Expect("Dropbox", amount="119.88", currency="USD", period="1y", next="2027-10-18",
                      category="cloud"),
    ),
    Email(
        "en_jetbrains_yearly", "en", "sales@jetbrains.com", "JetBrains Sales",
        "Your JetBrains All Products Pack subscription has been renewed", "2026-10-20T09:00:00+00:00",
        text="Subscription: All Products Pack, 1 year\nTotal: EUR 289.00 (VAT included)\n"
             "Valid until: October 20, 2027",
        expect=Expect("JetBrains", amount="289.00", currency="EUR", period="1y", next="2027-10-20"),
    ),
    Email(
        "en_xbox_game_pass", "en", "microsoft-noreply@microsoft.com", "Microsoft",
        "Your Xbox Game Pass Ultimate subscription", "2026-10-09T05:00:00+00:00",
        text="Thank you for your purchase of Xbox Game Pass Ultimate (1 month).\n"
             "Your subscription will automatically renew on 11/09/2026 for ₸1,899.00.",
        expect=Expect("Xbox Game Pass", amount="1899.00", currency="KZT", period="1m",
                      next="2026-11-09", category="games"),
    ),
    Email(
        "en_notion_trial", "en", "team@makenotion.com", "Notion Team",
        "Your Notion Plus trial ends in 3 days", "2026-10-22T07:00:00+00:00",
        text="Your free trial of Notion Plus ends on October 25, 2026. After that, you'll be charged "
             "$10.00 per month.",
        expect=Expect("Notion", kind="trial", amount="10.00", currency="USD", period="1m",
                      trial_until="2026-10-25"),
    ),
    Email(
        "en_adobe_cancel", "en", "mail@mail.adobe.com", "Adobe",
        "Your Adobe plan has been cancelled", "2026-10-17T15:00:00+00:00",
        text="We're sorry to see you go. Your Creative Cloud Photography plan has been cancelled and "
             "will not renew.",
        expect=Expect("Adobe Creative Cloud", kind="cancellation"),
    ),
    Email(
        "en_amazon_order", "en", "auto-confirm@amazon.com", "Amazon.com",
        "Your Amazon.com order #112-3344556-7788990", "2026-10-13T20:00:00+00:00",
        text="Thanks for your order. Order Total: $34.99. Your package will be shipped soon.",
        expect=None,
    ),
    Email(
        "en_medium_digest", "en", "noreply@medium.com", "Medium Daily Digest",
        "Stories for you", "2026-10-21T06:00:00+00:00",
        text="Become a member for $5/month and read unlimited stories. Unsubscribe.",
        headers={"List-Unsubscribe": "<https://medium.com/unsub>"},
        expect=None,
    ),
    Email(
        "en_tasklane_unknown", "en", "billing@tasklane.io", "Tasklane",
        "Receipt from Tasklane", "2026-10-03T11:00:00+00:00",
        text="Receipt #1042\nTasklane Pro (monthly)\nAmount paid: $8.00\nPaid on October 3, 2026",
        expect=Expect("Tasklane", amount="8.00", currency="USD", period="1m", status="review"),
    ),
    Email(
        "en_duolingo_annual", "en", "no-reply@duolingo.com", "Duolingo",
        "Your Super Duolingo subscription receipt", "2026-10-10T10:00:00+00:00",
        text="Super Duolingo — 12 months\nTotal: 15 990 ₸\nYour subscription will renew on "
             "October 10, 2027.",
        expect=Expect("Duolingo Super", amount="15990", currency="KZT", period="1y", next="2027-10-10",
                      category="education"),
    ),
    Email(
        "en_youtube_google", "en", "payments-noreply@google.com", "Google Payments",
        "Your YouTube Premium membership receipt", "2026-10-08T13:00:00+00:00",
        text="YouTube Premium (monthly)\nTotal: $13.99/mo\nNext billing date: Nov 8, 2026",
        expect=Expect("YouTube Premium", amount="13.99", currency="USD", period="1m", next="2026-11-08",
                      category="video"),
    ),
    # ----------------------------------------------------------------- kk
    Email(
        "kk_yandex_plus_kaspi", "kk", "noreply@kaspi.kz", "Kaspi.kz",
        "Төлем сәтті өтті", "2026-10-10T09:00:00+05:00",
        text="Яндекс Плюс жазылымы үшін төлем сәтті өтті.\nСома: 2 490 ₸\n"
             "Келесі төлем күні: 2026 жылғы 10 қараша\nАйына автоматты түрде ұзартылады.",
        expect=Expect("Яндекс Плюс", amount="2490", currency="KZT", period="1m", next="2026-11-10",
                      status="review"),
    ),
    Email(
        "kk_beeline_monthly", "kk", "info@beeline.kz", "Beeline Kazakhstan",
        "Ай сайынғы төлем", "2026-10-01T06:00:00+05:00",
        text="Сіздің тарифіңіз бойынша ай сайынғы төлем есептен шығарылды: 3 290 ₸.\n"
             "Келесі есептен шығару: 2026 жылғы 1 қараша.",
        expect=Expect("Beeline", amount="3290", currency="KZT", period="1m", next="2026-11-01"),
    ),
    Email(
        "kk_kcell_renewal", "kk", "noreply@kcell.kz", "Kcell",
        "Жазылым ұзартылады", "2026-10-22T08:00:00+05:00",
        text="Құрметті абонент! Сіздің «Kcell Music» жазылымыңыз 2026 жылғы 28 қазанда ұзартылады. "
             "Құны: 990 ₸ айына.",
        expect=Expect("Kcell", kind="renewal", amount="990", currency="KZT", period="1m",
                      next="2026-10-28"),
    ),
    Email(
        "kk_spotify_receipt", "kk", "no-reply@spotify.com", "Spotify",
        "Spotify Premium түбіртегі", "2026-10-12T15:00:00+05:00",
        text="Төлеміңіз үшін рахмет!\nPremium Individual: 1 590 ₸ / ай\n"
             "Келесі төлем: 2026 жылғы 12 қараша",
        expect=Expect("Spotify", amount="1590", currency="KZT", period="1m", next="2026-11-12"),
    ),
    Email(
        "kk_duolingo_trial", "kk", "no-reply@duolingo.com", "Duolingo",
        "Тегін сынақ кезеңі басталды", "2026-10-22T09:00:00+05:00",
        text="Super Duolingo сынақ кезеңі 2026 жылғы 5 қарашада аяқталады. "
             "Одан кейін жылына 15 990 ₸ есептен шығарылады.",
        expect=Expect("Duolingo Super", kind="trial", amount="15990", currency="KZT", period="1y",
                      trial_until="2026-11-05"),
    ),
    Email(
        "kk_kazakhtelecom_invoice", "kk", "info@telecom.kz", "Казахтелеком",
        "Интернет үшін шот", "2026-10-02T07:00:00+05:00",
        text="Қазан айы үшін шот: 6 500 ₸.\nТөлем мерзімі: 2026 жылғы 25 қазан дейін.",
        expect=Expect("Казахтелеком", kind="renewal", amount="6500", currency="KZT", period="1m",
                      next="2026-10-25"),
    ),
    Email(
        "kk_netflix_cancel", "kk", "info@account.netflix.com", "Netflix",
        "Жазылым тоқтатылды", "2026-10-21T21:00:00+05:00",
        text="Сіздің Netflix жазылымыңыз тоқтатылды. Ол 2026 жылғы 1 қарашада аяқталады.",
        expect=Expect("Netflix", kind="cancellation"),
    ),
    Email(
        "kk_kaspi_otp", "kk", "noreply@kaspi.kz", "Kaspi.kz",
        "Растау коды", "2026-10-21T12:00:00+05:00",
        text="Растау коды: 4417. Оны ешкімге айтпаңыз.",
        expect=None,
    ),
    Email(
        "kk_halyk_mixed", "kk", "noreply@halykbank.kz", "Halyk Bank",
        "Списание по подписке / Жазылым бойынша төлем", "2026-10-25T10:00:00+05:00",
        text="Netflix: 3 990 ₸ списано с карты *1234 / картадан есептен шығарылды.",
        expect=Expect("Netflix", amount="3990", currency="KZT", period="1m", status="review"),
    ),
]
