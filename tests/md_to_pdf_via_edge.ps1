# Regenerate schema_documentation.pdf from schema_documentation.md
# using pandoc (MD->HTML) + Edge headless (HTML->PDF). No LaTeX or Word needed.

$pandoc = 'C:\Users\Spencer\AppData\Local\Pandoc\pandoc.exe'
$edge   = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$root   = Split-Path -Parent $PSScriptRoot   # project root (this script lives in tests/)

# Simple, clean CSS for the HTML (Word-like print style).
$css = @'
<style>
  body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; line-height: 1.4; max-width: 7.5in; margin: 0.5in auto; color: #222; }
  h1 { font-size: 20pt; border-bottom: 2px solid #444; padding-bottom: 4pt; }
  h2 { font-size: 14pt; margin-top: 18pt; color: #333; }
  h3 { font-size: 12pt; margin-top: 14pt; color: #555; }
  table { border-collapse: collapse; margin: 8pt 0; font-size: 10pt; }
  th, td { border: 1px solid #aaa; padding: 4pt 8pt; text-align: left; vertical-align: top; }
  th { background: #eee; }
  code { font-family: Consolas, "Courier New", monospace; font-size: 9.5pt; background: #f4f4f4; padding: 1pt 3pt; border-radius: 2pt; }
  pre { background: #f4f4f4; padding: 8pt; border-left: 3px solid #888; overflow-x: auto; font-size: 9pt; }
  pre code { background: none; padding: 0; }
  img { max-width: 100%; }
  hr { border: 0; border-top: 1px solid #ccc; margin: 16pt 0; }
</style>
'@

$mdPath   = Join-Path $root 'schema_documentation.md'
$pdfPath  = Join-Path $root 'schema_documentation.pdf'
$htmlPath = Join-Path $root 'schema_documentation.html'

# MD -> HTML (standalone, with embedded CSS).
& $pandoc $mdPath -o $htmlPath --standalone --metadata title='' --resource-path="$root"
$html = Get-Content $htmlPath -Raw
$html = $html -replace '</head>', ($css + '</head>')
Set-Content -Path $htmlPath -Value $html -Encoding UTF8

# HTML -> PDF via Edge headless.
$fileUri = 'file:///' + $htmlPath.Replace('\', '/')
& $edge --headless --disable-gpu --no-pdf-header-footer --print-to-pdf="$pdfPath" $fileUri 2>$null
Start-Sleep -Seconds 3
Remove-Item $htmlPath -Force -ErrorAction SilentlyContinue

if (Test-Path $pdfPath) {
    $size = (Get-Item $pdfPath).Length
    Write-Output ("OK -> {0} ({1:N1} KB)" -f [System.IO.Path]::GetFileName($pdfPath), ($size/1KB))
} else {
    Write-Output ("FAILED to create {0}" -f $pdfPath)
}
