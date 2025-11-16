from typing import Optional
from pydantic import BaseModel, Field

class TransactionRow(BaseModel):
    """
    A structured schema for an individual financial transaction row,
    matching the LLM's typical output field names.
    """
    post_date: str = Field(description="The date the transaction was posted (e.g., '15-05-2020').")
    value_date: str = Field(description="The value date of the transaction (e.g., '15-05-2020').")
    description: str = Field(description="The full, detailed description of the transaction.")
    debit: float = Field(description="The debit amount, as a float (0.00 if it was a credit or not applicable).")
    credit: float = Field(description="The credit amount, as a float (0.00 if it was a debit or not applicable).")
    balance: float = Field(description="The account balance after the transaction, as a float.")
    reference_or_cheque_no: Optional[str] = Field(
        description="The cheque or transaction reference number, if available.", default=None
    )