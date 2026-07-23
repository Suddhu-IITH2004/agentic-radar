"""Input and intermediate app-related models."""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ctie.models.enums import SourceType


class AppInput(BaseModel):
    """A single app from the research set."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(..., description="Stable numeric identifier from the assignment.")
    name: str = Field(..., min_length=1, description="App name.")
    website: HttpUrl = Field(..., description="Primary website or docs URL.")
    category_hint: str = Field(..., description="Expected category from the assignment.")
    hints: list[str] = Field(default_factory=list, description="Additional search hints.")


class SearchResult(BaseModel):
    """A candidate URL discovered for an app."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    title: str | None = Field(default=None, description="Search result title.")
    url: HttpUrl = Field(..., description="Discovered URL.")
    source_type: SourceType = Field(default=SourceType.UNKNOWN, description="Classified source type.")
    position: int = Field(default=0, ge=0, description="Original search result position.")
    query: str = Field(default="", description="Query that produced this result.")

    def __hash__(self) -> int:
        return hash(str(self.url))


class Document(BaseModel):
    """A fetched and cleaned document."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: HttpUrl = Field(..., description="Source URL.")
    cleaned_text: str = Field(..., description="Cleaned markdown/text content.")
    title: str | None = Field(default=None, description="Page title.")
    fetch_method: str = Field(default="composio", description="One of composio, cache.")
    status_code: int | None = Field(default=None, description="HTTP status code if fetched live.")
    fetched_at: str | None = Field(default=None, description="ISO timestamp of fetch.")
    content_length: int = Field(default=0, ge=0, description="Length of cleaned text in bytes.")
