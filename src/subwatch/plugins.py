"""Public API for source plugins.

    from subwatch.plugins import RawMessage, Source, SourceContext, Transaction, source

    @source("my_bank")
    class MyBank(Source):
        kind = "transactions"

        def fetch(self, ctx: SourceContext):
            yield Transaction(date=..., amount=..., currency="KZT", merchant="NETFLIX.COM")

Options for a plugin live in config.toml under [plugins.options.<name>] and
reach the plugin as ctx.options.
"""

from .models import RawMessage, Transaction
from .sources.base import Source, SourceContext, source

__all__ = ["RawMessage", "Source", "SourceContext", "Transaction", "source"]
