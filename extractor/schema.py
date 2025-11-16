from typing import Optional
from pydantic import BaseModel, Field

class FinancialTransactionRow(BaseModel):
    """Schema for a single transaction row in the bank statement."""
    date: str = Field(description="The date of the transaction, kept in its original format.")
    reference_or_cheque_no: Optional[str] = Field(
        default=None,
        description="Reference or cheque number, if available."
    )
    description: str = Field(description="Detailed description of the transaction.")
    withdrawal_amount: Optional[float] = Field(
        default=None,
        description="The amount withdrawn (debit), if applicable. Positive number."
    )
    credit_amount: Optional[float] = Field(
        default=None,
        description="The amount credited, if applicable. Positive number."
    )
    balance: float = Field(description="The running balance after the transaction.")