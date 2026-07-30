# Render Dashboard and Custom Domain Deployment

## 1. Security preparation

Rotate the Render PostgreSQL password if it has been shared outside Render.
Never add a database URL to this repository, `render.yaml`, or a committed
configuration file.

## 2. Create the web service

Push the validated repository to GitHub, then create a Render Blueprint from
the repository. The checked-in `render.yaml` creates:

- a Python Streamlit web service;
- a Singapore-region runtime colocated with PostgreSQL;
- a health check at `/_stcore/health`;
- the custom domain request for
  `market-intelligence.niftydata.com.au`.

When Render requests the unsynchronised `DATABASE_URL` value, copy the exact
**Internal Database URL** from the Render PostgreSQL Connect page. Do not
construct the URL manually. Internal connectivity is preferred because both
services are in Singapore.

If creating the service manually instead of using the Blueprint:

- Runtime: Python
- Region: Singapore
- Build command: `pip install .`
- Start command:
  `streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true`
- Health check: `/_stcore/health`
- Environment variable: `DATABASE_URL` set to the internal PostgreSQL URL

## 3. Add the custom domain in Render

After the first successful deployment, open:

```text
Web service > Settings > Custom Domains
```

Confirm or add:

```text
market-intelligence.niftydata.com.au
```

Render will display the exact DNS destination for the service.

## 4. Add the DNS record

At the DNS provider for `niftydata.com.au`, add:

| Field | Value |
|---|---|
| Type | `CNAME` |
| Name / Host | `market-intelligence` |
| Target / Value | the service's Render `onrender.com` hostname |
| TTL | Auto or 300 seconds |

Enter only the hostname as the target: no `https://`, path, or trailing slash.

Remove any conflicting `A`, `AAAA`, or `CNAME` record for the exact
`market-intelligence` host. Do not change the root `niftydata.com.au` records,
nameservers, email records, or existing website hosting.

For Cloudflare-managed DNS, use **DNS only** while Render verifies the domain
and issues its certificate. Cloudflare SSL mode should be **Full**. Proxying can
be reconsidered after verification.

## 5. Verify and test

Return to Render and select **Verify** for the custom domain. Render provisions
and renews TLS automatically.

Verify:

- the `onrender.com` URL loads successfully;
- the custom HTTPS URL loads successfully;
- no database credentials appear in logs or error messages;
- the dashboard freshness date matches the curated database;
- the free-service cold start is understood before the interview.

Official references:

- <https://render.com/docs/web-services>
- <https://render.com/docs/custom-domains>
