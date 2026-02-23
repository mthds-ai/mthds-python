from pydantic import BaseModel, ConfigDict


class BundleMetadata(BaseModel):
    """Minimal metadata about a bundle needed for visibility checking.

    Attributes:
        domain: The domain path this bundle belongs to (e.g. "legal.contracts").
        main_pipe: The main_pipe code if declared (auto-exported), or None.
        pipe_references: List of (pipe_ref_str, context) pairs representing
            all pipe references found in this bundle.
    """

    model_config = ConfigDict(frozen=True)

    domain: str
    main_pipe: str | None = None
    pipe_references: list[tuple[str, str]] = []
