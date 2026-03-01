# Disclaimer & Risk Warning

**Please read this entire document before deploying or using this software.**

---

## Independent Project

This is an independent, community-driven open source project. It is **not affiliated with, endorsed by, sponsored by, or officially connected to Intuit Inc., QuickBooks, or Anthropic PBC** in any way. QuickBooks is a registered trademark of Intuit Inc. Claude is a product of Anthropic PBC. All trademarks belong to their respective owners.

---

## What This Software Does

This tool connects directly to the QuickBooks API using your credentials and can **read, create, modify, and delete financial data** in your QuickBooks account. This includes but is not limited to:

- Querying transactions, invoices, bills, customers, vendors, and accounts
- Creating and updating transaction categorizations
- Modifying existing records through the QuickBooks API
- Deleting or altering financial data when instructed by an MCP client or the automated scheduler

**Any changes made to your QuickBooks data through this tool are real and may be difficult or impossible to undo.**

---

## No Warranty

This software is provided **"AS IS"**, without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. The entire risk as to the quality and performance of this software is with you.

---

## Limitation of Liability

In no event shall the authors, contributors, or maintainers of this project be held liable for any claim, damages, or other liability arising from the use of this software. This includes but is not limited to:

- **Data loss** or corruption in your QuickBooks account
- **Incorrect transaction categorizations** applied automatically or manually
- **Tax filing errors** resulting from miscategorized transactions
- **Audit issues** caused by inaccurate or incomplete financial records
- **Financial harm** of any kind, whether direct, indirect, incidental, or consequential
- **Unauthorized access** to your QuickBooks data due to misconfiguration

**You use this software entirely at your own risk.**

---

## AI Categorization Is Not Accounting Advice

The automated scheduler uses AI (Claude by Anthropic) to categorize financial transactions. While AI can be a helpful tool, it is important to understand that:

- AI categorization is **not a substitute for a licensed accountant, CPA, or professional bookkeeper**
- AI models can and do make mistakes, including confidently incorrect categorizations
- Categorization rules learned by the AI may not reflect current tax law or your specific business requirements
- The AI does not understand your full financial context and may misinterpret transactions
- Automated categorizations should always be reviewed by a qualified human before being used for tax filing, financial reporting, or business decisions

**You are solely responsible for reviewing all AI-generated categorizations before relying on them for any purpose.**

---

## Automated Scheduler Warning

When the scheduler is enabled, it runs autonomously on a configured schedule and will:

- Connect to your QuickBooks account without prompting you each time
- Pull transaction data and send it to the Anthropic API for AI analysis
- Apply categorizations back to QuickBooks **without human approval for each individual action**
- Flag certain transactions for review, but process others automatically

Before enabling the scheduler:

1. **Maintain current QuickBooks backups.** Ensure you have a reliable backup strategy in place before enabling any automated features. QuickBooks Online has limited undo capabilities.
2. **Start with the scheduler disabled.** Review the categorization rules and test with manual runs before enabling automatic scheduling.
3. **Review flagged items regularly.** The system flags uncertain categorizations, but it may also auto-categorize transactions that warranted human review.
4. **Monitor run history.** Check the admin portal dashboard and run history after each automated run to verify results.

---

## Test Before Production

**Always test in a QuickBooks Sandbox environment first** before connecting this tool to your production QuickBooks account. The sandbox provides a safe environment to:

- Verify that API connections work correctly
- Review how the AI categorizes sample transactions
- Confirm that categorization rules behave as expected
- Understand what data the tool reads and modifies

Only connect to production data after you are confident the tool behaves correctly in sandbox mode and you have backups in place.

---

## Data Privacy

When using the automated scheduler:

- Your QuickBooks transaction data is sent to the Anthropic API for processing
- Review Anthropic's data usage and privacy policies to understand how your data is handled
- You are responsible for ensuring this data handling complies with any applicable regulations (GDPR, CCPA, etc.) and your own data governance requirements
- The admin portal stores your Anthropic API key (encrypted) and QuickBooks credentials in a local SQLite database — secure this appropriately

---

## Your Responsibility

By using this software, you acknowledge and accept that:

1. You have read and understood this disclaimer in its entirety
2. You are solely responsible for any changes made to your QuickBooks data
3. You will maintain adequate backups before using automated features
4. You will review AI-generated categorizations before using them for tax or financial purposes
5. You will not hold the authors or contributors liable for any damages
6. You understand that this is not professional accounting software and does not replace professional advice

---

## USE AT YOUR OWN RISK

This tool is powerful and can save significant time when used responsibly. It can also cause real harm to your financial records if misconfigured or used without proper oversight. Please use it thoughtfully, maintain backups, and always have a qualified professional review your financial records.

---

*This disclaimer applies to all versions of this software and all methods of deployment (Docker, local, or otherwise).*
