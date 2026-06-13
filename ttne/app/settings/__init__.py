def __getattr__(name):
    if name == "router":
        from .routers import router

        return router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
