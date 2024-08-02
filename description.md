Easily create BTCPayServer-style invoices that support Lightning Network and on-chain BTC payment.

Works with the Onchain wallet extension for onchain addressses.

features:

- set a description for the payment
- the amount in sats
- the time, in minutes, the invoice is valid for, after this period the invoice can't be paid

Advanced (optional):

- set a webhook that will get the transaction details after a successful payment
- set to where the user should redirect after payment
- set the text for the button that will show after payment (not setting this, will display "NONE" in the button)
- select if you want on-chain payment, LN payment or both
- depending on what you select you'll have to choose the respective wallets where to receive your payment
