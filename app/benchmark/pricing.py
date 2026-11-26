from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ModelPricing:
    input_usd_per_million: float
    output_usd_per_million: float

    def __post_init__(self) -> None:
        if self.input_usd_per_million < 0 or self.output_usd_per_million < 0:
            raise ValueError("Model token prices cannot be negative")

    def estimate(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_usd_per_million + output_tokens * self.output_usd_per_million) / 1_000_000
