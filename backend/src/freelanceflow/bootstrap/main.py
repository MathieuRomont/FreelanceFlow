"""HTTP entry point; business modules will be composed here when implemented."""

from fastapi import FastAPI

app = FastAPI(title="FreelanceFlow")


@app.get("/health")
def health() -> dict[str, str]:
    """Report process liveness without querying external services."""
    return {"status": "healthy"}
