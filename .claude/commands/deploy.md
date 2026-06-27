Deploy the Slipcast app to production.

If $ARGUMENTS is provided, use it as the version tag (e.g. `v1.2.0`). Otherwise determine the next patch version from the latest git tag.

Steps:

1. **Verify clean state** — run `git status` and confirm there are no uncommitted changes. If there are, stop and tell the user.

2. **Determine version** — if no version was passed, run `git tag --sort=-v:refname | head -5` to see recent tags and suggest the next patch version. Confirm with the user before proceeding.

3. **Tag the release** — run `git tag <version>` and `git push origin <version>` to trigger the Docker Hub CI build.

4. **Watch the build** — get the latest run ID with `gh run list --limit 1 --json databaseId -q '.[0].databaseId'` and watch it with `gh run watch <id> --exit-status`. Wait for it to complete successfully before continuing.

5. **Pull and restart** — run `docker compose pull && docker compose up -d` from the project directory `/home/eric/projects/slipcast`.

6. **Confirm** — report the version deployed and confirm the container is running.
