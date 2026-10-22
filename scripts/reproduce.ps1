# Full pipeline, in dependency order. Stops at the first failing step.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
function Step($cmd) { Write-Host ">> $cmd"; Invoke-Expression $cmd; if ($LASTEXITCODE) { Write-Error "failed: $cmd"; exit 1 } }
Step "python -m pytest"
Step "python scripts/tune.py"                       # dev seeds; must reproduce config/tuned_params.json
Step "python scripts/run_experiments.py"            # E1-E10, reported seeds
Step "python scripts/e9_control.py"                 # E9C control (needs E9)
Step "python scripts/run_experiments.py DEVD"       # dev-seed check for DR-DRR+damping
Step "python scripts/confirm_damping.py"            # pre-registered rule; non-zero exit stops here
Step "python scripts/run_experiments.py E1D"        # DR-DRR+damping on reported seeds
Step "python scripts/run_experiments.py E1V"        # superseded CQDRR draft, for comparison
Step "python scripts/run_experiments.py ES"         # SCRR, optional ninth scheduler
Step "python scripts/run_experiments.py E11"        # real-life stress scenarios
Step "python scripts/run_experiments.py E12"        # more real-life conditions + checks of the method
Step "python scripts/timeseries.py"
Step "python scripts/make_figures.py"
Step "python scripts/make_report.py"
