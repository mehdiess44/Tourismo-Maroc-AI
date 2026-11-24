$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$securePassword = Read-Host 'Mot de passe PostgreSQL local (saisie masquee)' -AsSecureString
$secretPointer = [IntPtr]::Zero
try {
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
    $encodedPassword = [System.Uri]::EscapeDataString($plainPassword)
    $env:TOURISMO_DB_PASSWORD = $plainPassword
    $env:TOURISMO_DATABASE_URL = ('postgresql://tourismo:{0}@127.0.0.1:5432/tourismo' -f $encodedPassword)
    $plainPassword = $null
    $encodedPassword = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    $secretPointer = [IntPtr]::Zero
    & (Join-Path $repo '.venv\Scripts\python.exe') -m scripts.lot4_official_benchmark
    if ($LASTEXITCODE -ne 0) {
        throw ('Benchmark officiel interrompu. Code Python : {0}' -f $LASTEXITCODE)
    }
    Write-Host 'Benchmark officiel termine. Voir data/lot-4/b-official-benchmark-conditions-v2.json.'
}
finally {
    if ($secretPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    }
    Remove-Item Env:TOURISMO_DB_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:TOURISMO_DATABASE_URL -ErrorAction SilentlyContinue
    $plainPassword = $null
    $encodedPassword = $null
    $securePassword = $null
}
