# Development

Keep changes small, commit and push frequently, and use pull requests.
After creating a PR or pushing a new revision, the manager uses the installed
`pr-watch` skill with gpt-5.6-luna at low effort. The watcher only reports; it
does not change code or post comments. Detect CI and actual bot presence.

Run `python -m unittest discover -s tests -v` before pushing code changes.
Keep benchmarks in separate `benchmarks/<test>/rounds/<round>/` directories.
Never rewrite archived results. Distinguish inferred links from observed execution.
Never claim a provider score is a calibrated probability or a missing edge
proves a test is irrelevant. Preserve ordinary search and test fallbacks.

## Secrets

Never ask for secrets in chat. Use `tokenstash need TYPESAFE_API_KEY`.
Exit 0: continue with the project env file; 10: pending, do independent work;
20: denied, use a non-secret fallback. Never commit env files or local maps.
