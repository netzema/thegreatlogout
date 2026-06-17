# The Great Logout Email Worker

This Worker receives guide signups from `thegreatlogout.org`, stores them in Cloudflare D1, and sends the email sequence through Postmark from:

```txt
The Great Logout <hello@thegreatlogout.org>
```

## What it sends

- Day 0 through Day 7
- Day 14
- Day 30
- Month 6
- Year 1

Each email includes:

- the guide text
- three ready-to-use post options
- links to open each option in the website post generator
- direct square and vertical SVG download links for each option
- an unsubscribe link

The direct SVG endpoint is:

```txt
https://api.thegreatlogout.org/post.svg?text=...
https://api.thegreatlogout.org/post.svg?text=...&format=vertical
```

## Setup

1. Install Wrangler:

```bash
npm install -g wrangler
```

2. Log in:

```bash
wrangler login
```

3. Create the D1 database:

```bash
cd worker
wrangler d1 create thegreatlogout-email
```

Copy the returned `database_id` into `wrangler.toml`.

4. Apply the schema:

```bash
wrangler d1 execute thegreatlogout-email --file=./schema.sql --remote
```

5. Add the Postmark token as a secret:

```bash
wrangler secret put POSTMARK_SERVER_TOKEN
```

Use the Postmark server token for the server that has `hello@thegreatlogout.org` configured.

6. Deploy:

```bash
wrangler deploy
```

7. Add a route/custom domain in Cloudflare:

```txt
api.thegreatlogout.org
```

The website form currently posts to:

```txt
https://api.thegreatlogout.org/subscribe
```

## Local notes

Do not put the Postmark token into `index.html`. Browser JavaScript is public. The token belongs only in Worker secrets.

## Send a test email without Cloudflare

From the repository root:

```bash
python scripts/send_postmark_email.py --list
python scripts/send_postmark_email.py --key day-1 --first-name Daniel
```

The script reads `POSTMARK_SERVER_TOKEN` and `TEST_RECIPIENT` from your local `.env` file or from the environment. You can still override the recipient with `--to`.

Use `--dry-run` to preview the Postmark payload without sending:

```bash
python scripts/send_postmark_email.py --key day-14 --dry-run
```
