from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):

    model_config = SettingsConfigDict(
        env_file= ".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

    paper_trade: bool = Field(default=False, alias="PAPER_TRADE")
    max_open_positions: int = Field(default=10, alias="MAX_OPEM_POSITIONS")



    db_url: str = Field(..., alias="DB_URL")



config = Config()
