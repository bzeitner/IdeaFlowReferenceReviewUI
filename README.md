# IdeaFlow Reference Review UI

A local-only Django interface for reviewing IdeaFlow calibration packets. It supports both independent blinded packets and explicit model-assisted error-audit packets. In assisted mode, reviewers mark each automated criterion judgment correct or wrong and provide corrections only where needed.

The app does not connect to IdeaFlow, call a model, browse sources, or submit reviews. The operator separately imports completed assessments with human attestation.

## Start locally

Requires Python 3.12 or newer.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/>. Import only the archive assigned to that reviewer:

- Brad: `r5a-plan-1-brad-id7.tar.gz`
- Zak: `r5a-plan-1-zak-id5.tar.gz`

Use separate computers or separate database paths so one reviewer cannot see the other's saved judgments:

```sh
REVIEW_UI_DATABASE=/private/path/brad-review.sqlite3 .venv/bin/python manage.py migrate
REVIEW_UI_DATABASE=/private/path/brad-review.sqlite3 .venv/bin/python manage.py runserver 127.0.0.1:8000
```

## Review rules

- Use only the evidence included in each packet. Do not browse or add outside knowledge.
- Review independently; do not share judgments before both reviewers finish.
- Choose `pass` or `fail` only when the selected packet references cover every evidence kind required by the criterion.
- Choose `not applicable` when the criterion genuinely does not apply.
- Choose `insufficient evidence` when it applies but required evidence is absent.
- Give every criterion a concise reason.
- Quality-rubric exports always use `"progress_score": null`.

In model-assisted mode, the reviewer must explicitly mark every automated criterion result correct or wrong. Each case export is an importer-compatible envelope containing the exact automated-result fingerprint, final assessment, and difference manifest. The ZIP also includes `assisted-review-audit.json`, which summarizes the automated response and every reviewer correction. Assisted results are diagnostic error-audit evidence, not unbiased human–model agreement.

After all cases are complete, export the assessment ZIP. Send that ZIP to the trusted operator; do not edit the generated JSON.

## Sensitive local data

Packet content and draft assessments are stored in `review-data.sqlite3` by default. The database, archives, and ZIP exports are ignored by Git. Use the **Delete local bundle** action after the operator confirms successful import, then securely remove the original archive and exported ZIP according to the pilot retention policy.

Bind the development server only to `127.0.0.1`. This app is intentionally not configured for network deployment.

## Tests

```sh
.venv/bin/python manage.py test
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
```
