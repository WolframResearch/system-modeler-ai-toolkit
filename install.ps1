<#
.SYNOPSIS
  Install the System Modeler agent skills into a Claude Code skills directory.

.DESCRIPTION
  Links (or copies) BOTH the per-skill directories AND the shared scripts/ folder
  into the target. Installing the skills without scripts/ is the #1 cause of
  "wsm_run.py not found": every SKILL.md refers to the launcher as
  ../scripts/wsm_run.py, so scripts/ must sit alongside the skill dirs.

  Linking uses directory junctions (cmd /c mklink /J), which need neither Developer
  Mode nor an elevated shell. This deliberately avoids New-Item -ItemType SymbolicLink:
  on Windows PowerShell 5.1 that cmdlet ignores the Developer Mode unprivileged-symlink
  flag and fails without elevation (only PowerShell 7+ / cmd's mklink honour it). A
  junction behaves like a symlink for read access, so edits in the repo still show up
  in the installed skill. If a junction cannot be created for an item (e.g. the target
  is on a network share), that item is copied instead. Use -Copy to copy everything.

  An existing entry in the target is replaced only when it is a junction/symlink that
  points back into this repo (i.e. a previous install by this script). Anything else
  is left untouched with a warning; pass -Force to replace it anyway.

.EXAMPLE
  ./install.ps1
  ./install.ps1 -Target "C:\Users\me\.claude\skills"
  ./install.ps1 -Copy
  ./install.ps1 -Force
#>
param(
  [string]$Target = (Join-Path $HOME ".claude\skills"),
  [switch]$Copy,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

# This script is Windows-only: linking relies on directory junctions created via
# cmd /c mklink. On Linux/macOS use ./install.sh instead.
if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) {
  Write-Host "ERROR: install.ps1 is Windows-only (it uses cmd /c mklink junctions); on this OS run ./install.sh instead."
  exit 2
}

$RepoRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))

# Discover the skill dirs from disk (any dir with a SKILL.md) so new skills are
# picked up automatically and this list can't drift from what's in the repo.
$Items = @(
  Get-ChildItem -LiteralPath $RepoRoot -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "SKILL.md") } |
    ForEach-Object { $_.Name }
)
$Items += "scripts"

function Get-LinkTarget($Item) {
  # The .Target of a junction/symlink is a string on PS 7+ but a string array on
  # 5.1, and may carry a \\?\ prefix or be relative. Normalize to one absolute
  # path, or $null if it cannot be read.
  $t = @($Item.Target) | Select-Object -First 1
  if (-not $t) { return $null }
  $t = [string]$t
  if ($t.StartsWith('\\?\')) { $t = $t.Substring(4) }
  if (-not [System.IO.Path]::IsPathRooted($t)) {
    $t = Join-Path (Split-Path -Parent $Item.FullName) $t
  }
  return [System.IO.Path]::GetFullPath($t)
}

function Resolve-PhysicalPath([string]$Path) {
  # Resolve-Path does NOT resolve junctions/symlinks, so it is not enough for
  # the self-install guard: normalize with GetFullPath, then walk reparse
  # points (via Get-Item .Target) until we reach a real directory.
  $full = [System.IO.Path]::GetFullPath($Path)
  for ($i = 0; $i -lt 32; $i++) {
    $item = Get-Item -LiteralPath $full -Force -ErrorAction SilentlyContinue
    if (-not $item -or -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { break }
    $next = Get-LinkTarget $item
    if (-not $next) { break }
    $full = $next
  }
  return $full
}

function Test-OwnedByRepo($Item) {
  # May we replace $Item silently? Only if it is a junction/symlink that points
  # back into this repo (a previous install), or a dangling one - typically a
  # leftover link after the repo was moved - whose removal loses nothing.
  if (-not ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return $false }
  $t = Get-LinkTarget $Item
  if (-not $t) {
    # Target unreadable: treat as ours only if the link is dangling.
    return [bool](-not (Test-Path -LiteralPath $Item.FullName))
  }
  $t = $t.TrimEnd('\', '/')
  $root = $RepoRoot.TrimEnd('\', '/')
  if ($t -ieq $root) { return $true }
  $sep = [string][System.IO.Path]::DirectorySeparatorChar
  if ($t.ToLowerInvariant().StartsWith(($root + $sep).ToLowerInvariant())) { return $true }
  if (-not (Test-Path -LiteralPath $t)) { return $true }   # dangling link
  return $false
}

function Remove-Existing([string]$Path) {
  # Get-Item -Force, NOT Test-Path: Test-Path returns $false for a dangling
  # junction (e.g. after the repo was moved), which would leave the stale link
  # in place and make the install of that item fail.
  $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
  if (-not $item) { return }
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    # A junction/symlink: remove the link itself via .Delete(), which unlinks the reparse
    # point only. NEVER use Remove-Item -Recurse here - in PS 5.1 that can follow the link
    # and delete the *target* (i.e. the repo) contents.
    $item.Delete()
  } else {
    Remove-Item -LiteralPath $Path -Recurse -Force
  }
}

function Copy-IntoPlace([string]$Src, [string]$Dst) {
  # Stage the copy under a temp name in the target dir, then swap it into place,
  # so a mid-copy failure never leaves the user with neither the old nor the new
  # entry.
  $tmp = Join-Path (Split-Path -Parent $Dst) (".{0}.installing.{1}" -f (Split-Path -Leaf $Dst), $PID)
  if (Get-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue) {
    Remove-Item -LiteralPath $tmp -Recurse -Force
  }
  try {
    Copy-Item -LiteralPath $Src -Destination $tmp -Recurse
  } catch {
    if (Get-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue) {
      Remove-Item -LiteralPath $tmp -Recurse -Force
    }
    throw
  }
  Remove-Existing $Dst
  Move-Item -LiteralPath $tmp -Destination $Dst
}

function New-DirJunction([string]$Link, [string]$TargetPath) {
  # Directory junction via cmd: no Developer Mode / elevation required, honoured by every
  # PowerShell edition. Pass the paths as separate arguments (PowerShell quotes each one
  # that contains spaces) rather than as one pre-quoted string, which PS 5.1 mangles when
  # handing it to cmd /c. Returns $true on success.
  $null = & cmd.exe /c mklink /J $Link $TargetPath 2>&1
  return ($LASTEXITCODE -eq 0)
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
# Refuse to install into the repo itself: dst would BE src, and replacing an
# "existing entry" below would delete the real skill sources. Resolve the target
# physically (junctions/symlinks included - a junction pointing at the repo must
# not slip through) and compare case-insensitively.
$ResolvedTarget = Resolve-PhysicalPath $Target
$ResolvedRepo = Resolve-PhysicalPath $RepoRoot
if ($ResolvedTarget.TrimEnd('\', '/') -ieq $ResolvedRepo.TrimEnd('\', '/')) {
  Write-Host "ERROR: target ($Target) is the repo folder itself; choose another -Target."
  exit 2
}
# Belt and braces: string comparison can miss exotic aliases (8.3 short names,
# subst drives), so also verify by identity - a marker file created in the
# target must not show up inside the repo.
try {
  $markerName = ".selfcheck." + [Guid]::NewGuid().ToString("N")
  $marker = Join-Path $Target $markerName
  New-Item -ItemType File -Path $marker | Out-Null
  $sameAsRepo = Test-Path -LiteralPath (Join-Path $RepoRoot $markerName)
  Remove-Item -LiteralPath $marker -Force
  if ($sameAsRepo) {
    Write-Host "ERROR: target ($Target) is the repo folder itself; choose another -Target."
    exit 2
  }
} catch {
  # Marker check is best-effort; the resolved-path comparison above still holds.
}
$mode = if ($Copy) { "copy" } else { "link (junction)" }
Write-Host "Installing skills from $RepoRoot"
Write-Host "                  into $Target   (mode: $mode)`n"

foreach ($item in $Items) {
  $src = Join-Path $RepoRoot $item
  $dst = Join-Path $Target $item
  if (-not (Test-Path -LiteralPath $src)) {
    Write-Host "  skip  $item  (not present in repo)"
    continue
  }
  # Replace an existing entry only when it is ours (a junction/symlink back into
  # this repo) - never silently delete something the user put there themselves.
  # Get-Item -Force so dangling junctions are seen too (Test-Path hides them).
  $existing = Get-Item -LiteralPath $dst -Force -ErrorAction SilentlyContinue
  if ($existing) {
    if (Test-OwnedByRepo $existing) {
      # our own link from a previous install; replace silently
    } elseif ($Force) {
      Write-Warning "replacing $dst (not installed from this repo) because of -Force"
    } else {
      Write-Warning "$dst exists and was not installed from this repo; skipping - remove it manually or re-run with -Force"
      continue
    }
  }
  if ($Copy) {
    Copy-IntoPlace $src $dst
    Write-Host "  copy  $item"
  } else {
    Remove-Existing $dst
    if (New-DirJunction -Link $dst -TargetPath $src) {
      Write-Host "  link  $item -> $src"
    } else {
      Copy-IntoPlace $src $dst
      Write-Host "  copy  $item  (junction unavailable; copied instead)"
    }
  }
}

Write-Host "`nDone. The launcher is reachable from each skill as ..\scripts\wsm_run.py"
Write-Host "Verify with:  python3 `"$Target\scripts\wsm_run.py`" --mode info  (or 'py -3' on Windows)"
