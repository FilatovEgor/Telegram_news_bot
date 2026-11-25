from pydantic import BaseModel, ConfigDict, Field


class ChannelVariants(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    telegram: str = Field(min_length=1, max_length=4000)
    brief: str = Field(min_length=1, max_length=2000)


class EditorialPackage(BaseModel):
    """Structured AI-produced editorial content; never represents publication approval."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    category: str = Field(min_length=1, max_length=64)
    language: str = Field(min_length=2, max_length=32)
    summary: str = Field(min_length=1, max_length=4000)
    key_points: list[str] = Field(default_factory=list, max_length=8)
    entities: list[str] = Field(default_factory=list, max_length=30)
    important_numbers: list[str] = Field(default_factory=list, max_length=30)
    channel_variants: ChannelVariants
    caveats: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)



class TranslationPackage(BaseModel):
    """English translation of an approved source-language editorial package."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    source_language: str = Field(min_length=2, max_length=16)
    language: str = Field(min_length=2, max_length=16)
    title: str = Field(min_length=1, max_length=1024)
    category: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=4000)
    key_points: list[str] = Field(default_factory=list, max_length=8)
    entities: list[str] = Field(default_factory=list, max_length=30)
    important_numbers: list[str] = Field(default_factory=list, max_length=30)
    channel_variants: ChannelVariants
    caveats: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)
