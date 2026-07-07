<a href="https://lnbits.com" target="_blank" rel="noopener noreferrer">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://i.imgur.com/QE6SIrs.png">
    <img src="https://i.imgur.com/fyKPgVT.png" alt="LNbits" style="width:280px">
  </picture>
</a>

[![License: MIT](https://img.shields.io/badge/License-MIT-success?logo=open-source-initiative&logoColor=white)](./LICENSE)
[![Built for LNbits](https://img.shields.io/badge/Built%20for-LNbits-4D4DFF?logo=lightning&logoColor=white)](https://github.com/lnbits/lnbits)

# SatsPay Server - [LNbits](https://lnbits.com) extension

Create payment pages that accept both Lightning and on-chain Bitcoin. Includes webhook support for integrating payments into your applications.

## How it works

Create charges with customizable amounts, expiry times, and payment options. Share the payment page with your customer. When paid, webhooks notify your backend and the user can be redirected to a success page.

## Features

- Lightning and on-chain payment support
- Configurable invoice expiry
- Webhook notifications on payment
- Custom redirect URLs after payment
- Payment status tracking
- BIP21 Support

## Usage

1. Create a new charge

   ![new charge](https://i.imgur.com/fUl6p74.png)

2. Fill out the invoice fields

   - Description for the payment
   - Amount in sats
   - Expiry time in minutes
   - Webhook URL for payment notifications
   - Redirect URL after successful payment
   - Button text for the success page
   - Select payment methods (on-chain, Lightning, or both)
   - Choose the receiving wallets

   ![charge form](https://i.imgur.com/F10yRiW.png)

3. The charge appears in the Charges section

   ![charges](https://i.imgur.com/zqHpVxc.png)

4. Your customer sees the payment page and can choose Lightning

   ![offchain payment](https://i.imgur.com/4191SMV.png)

   Or on-chain

   ![onchain payment](https://i.imgur.com/wzLRR5N.png)

5. Track payment status in LNbits

   ![invoice state](https://i.imgur.com/JnBd22p.png)

## Powered by LNbits

[LNbits](https://lnbits.com) is a free and open-source lightning accounts system.

[![Visit LNbits Shop](https://img.shields.io/badge/Visit-LNbits%20Shop-7C3AED?logo=shopping-cart&logoColor=white&labelColor=5B21B6)](https://shop.lnbits.com/)
[![Try myLNbits SaaS](https://img.shields.io/badge/Try-myLNbits%20SaaS-2563EB?logo=lightning&logoColor=white&labelColor=1E40AF)](https://my.lnbits.com/login)
