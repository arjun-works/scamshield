# Deploying ScamShield

Backend on Cloud Run (asia-south1), frontend on Firebase Hosting, data in Firestore, Gemini key in Secret Manager.

Run every command from the repo root in PowerShell. Project: `scamshield-510918`. The needed APIs (Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Firestore, Firebase Hosting) are already enabled and Firestore already holds the seeded demo data.

## What gets created

| Resource | Name |
|---|---|
| Service account for the backend | `scamshield-run@scamshield-510918.iam.gserviceaccount.com` |
| Secret | `gemini-api-key` |
| Cloud Run service | `scamshield-api` |
| Container image repository (created by the first deploy) | `cloud-run-source-deploy` in asia-south1 |
| Hosting site | https://scamshield-510918.web.app |

## Step 1: service account with Firestore access

The backend runs as its own service account, which can read and write Firestore and nothing else.

```powershell
gcloud iam service-accounts create scamshield-run --display-name "ScamShield Cloud Run" --project scamshield-510918
```

```powershell
gcloud projects add-iam-policy-binding scamshield-510918 --member "serviceAccount:scamshield-run@scamshield-510918.iam.gserviceaccount.com" --role roles/datastore.user --condition None
```

## Step 2: Gemini key in Secret Manager

This copies the key from `.env` into a secret without printing it, then lets the service account read that one secret. The temporary file is deleted straight away.

```powershell
$key = ((Get-Content .env | Where-Object { $_ -match '^GEMINI_API_KEY=' }) -replace '^GEMINI_API_KEY=', '').Trim(); [IO.File]::WriteAllText("$env:TEMP\gemini-key.txt", $key); gcloud secrets create gemini-api-key --data-file "$env:TEMP\gemini-key.txt" --replication-policy automatic --project scamshield-510918; Remove-Item "$env:TEMP\gemini-key.txt"
```

```powershell
gcloud secrets add-iam-policy-binding gemini-api-key --member "serviceAccount:scamshield-run@scamshield-510918.iam.gserviceaccount.com" --role roles/secretmanager.secretAccessor --project scamshield-510918
```

## Step 2b: admin token for the demo reset

`scripts/demo.py reset` calls `POST /admin/reset`, which only works when the backend has `ADMIN_TOKEN` set. This copies the token from `.env` into a second secret, the same way as the Gemini key.

```powershell
$token = ((Get-Content .env | Where-Object { $_ -match '^ADMIN_TOKEN=' }) -replace '^ADMIN_TOKEN=', '').Trim(); $tmp = Join-Path $env:TEMP 'admin-token.txt'; [IO.File]::WriteAllText($tmp, $token); gcloud secrets create admin-token --data-file $tmp --replication-policy automatic --project scamshield-510918; [IO.File]::Delete($tmp)
```

```powershell
gcloud secrets add-iam-policy-binding admin-token --member "serviceAccount:scamshield-run@scamshield-510918.iam.gserviceaccount.com" --role roles/secretmanager.secretAccessor --project scamshield-510918
```

## Step 3: build and deploy the backend

Cloud Build runs as the project's default compute service account. On this project it could not read the uploaded source until it was given the Cloud Run Builder role (the deploy failed with `storage.objects.get denied`). One-time grant:

```powershell
gcloud projects add-iam-policy-binding scamshield-510918 --member "serviceAccount:620072834746-compute@developer.gserviceaccount.com" --role roles/run.builder --condition None
```

Cloud Build builds the `Dockerfile` in the repo root and Cloud Run deploys it. The first run asks to create the image repository; answer `Y`. It takes several minutes.

```powershell
gcloud run deploy scamshield-api --source . --project scamshield-510918 --region asia-south1 --service-account scamshield-run@scamshield-510918.iam.gserviceaccount.com --allow-unauthenticated --min-instances 0 --max-instances 1 --memory 1Gi --cpu 1 --no-cpu-throttling --cpu-boost --timeout 300 --set-secrets "GEMINI_API_KEY=gemini-api-key:latest,ADMIN_TOKEN=admin-token:latest" --set-env-vars "^@^GOOGLE_CLOUD_PROJECT=scamshield-510918@STORE_BACKEND=firestore@CORS_ORIGINS=https://scamshield-510918.web.app,https://scamshield-510918.firebaseapp.com"
```

Why these settings:

- `--min-instances 0`: nothing runs, and nothing is billed, when nobody is using it. The first request after a quiet spell takes longer (cold start).
- `--max-instances 1`: the backend keeps Firestore data in memory and serves reads from there, so there must be only one instance.
- `--no-cpu-throttling`: Gemini investigations run in the background after the response is sent. Without this flag Cloud Run takes the CPU away between requests and they would stall. The instance is billed while it is up (it shuts down about 15 minutes after the last request).
- `--allow-unauthenticated`: the browser calls the API directly. See "Before you share the link" below.
- `^@^` in `--set-env-vars` switches the separator to `@`, because the CORS value contains a comma.

## Step 4: check the backend

```powershell
$api = gcloud run services describe scamshield-api --project scamshield-510918 --region asia-south1 --format "value(status.url)"; $api; (Invoke-RestMethod "$api/health").status; "customers: " + (Invoke-RestMethod "$api/customers").Count
```

Expected: the service URL, `ok`, and `customers: 30`.

## Step 5: build the frontend against that URL

```powershell
$api = gcloud run services describe scamshield-api --project scamshield-510918 --region asia-south1 --format "value(status.url)"; Set-Content -Path frontend\.env.production -Value "VITE_API_URL=$api" -Encoding ascii; Push-Location frontend; npm run build; Pop-Location
```

`frontend/.env.production` is gitignored. It holds only the public API address.

## Step 6: deploy the frontend

```powershell
firebase deploy --only hosting --project scamshield-510918
```

Then open https://scamshield-510918.web.app/customer and https://scamshield-510918.web.app/analyst.

## Updating later

- Backend code changed: run Step 3 again.
- Frontend code changed: run Steps 5 and 6 again.
- Reseeded Firestore: the backend loads data at startup, so restart it with `gcloud run services update scamshield-api --project scamshield-510918 --region asia-south1 --update-env-vars RELOADED_AT=$(Get-Date -Format o)`.
- Rotated the Gemini key: `gcloud secrets versions add gemini-api-key --data-file <file> --project scamshield-510918`, then restart as above.

## Cost

Everything here is meant to stay inside the free tiers for a demo, but two items are not strictly free:

- **Cloud Run with `--no-cpu-throttling`** bills for the whole time an instance is up, not only while it handles requests. An open browser tab polls every 4 seconds and keeps the instance up. The monthly free allowance covers many hours of this; close the tabs when you are done.
- **Artifact Registry** stores the container image. The free allowance is 0.5 GB and this image is larger, so expect a few cents a month until you delete it.

Check current allowances at https://cloud.google.com/run/pricing and https://cloud.google.com/artifact-registry/pricing before relying on these figures.

## Before you share the link

The API has no login. Anyone with the Cloud Run URL can read the demo data, create payments, use up the Gemini quota and write to Firestore. That is acceptable for a hackathon demo with synthetic data, and not for anything else. Take it down when the demo is over.

## Taking it down

```powershell
gcloud run services delete scamshield-api --project scamshield-510918 --region asia-south1
```

```powershell
firebase hosting:disable --project scamshield-510918
```

```powershell
gcloud artifacts repositories delete cloud-run-source-deploy --location asia-south1 --project scamshield-510918
```

```powershell
gcloud secrets delete gemini-api-key --project scamshield-510918
```
