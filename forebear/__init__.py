"""Forebear: check a medical device's 510(k) ancestry before you cite it as a predicate."""
try:  # use the OS certificate store (corporate proxies / Windows roots) when available
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover - optional
    pass
