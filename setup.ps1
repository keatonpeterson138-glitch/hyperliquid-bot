# Hyperliquid Trading Bot - Quick Setup Script
# Run this script to set up the bot in one go

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host "Hyperliquid Trading Bot - Quick Setup" -ForegroundColor Green
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host ""

# Step 1: Install dependencies
Write-Host "[1/4] Installing Python dependencies..." -ForegroundColor Yellow
py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Dependencies installed successfully" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to install dependencies" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 2: Create .env file if it doesn't exist
Write-Host "[2/4] Setting up configuration..." -ForegroundColor Yellow
if (-Not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "✓ Created .env file from template" -ForegroundColor Green
    Write-Host "⚠ IMPORTANT: Edit .env and add your credentials!" -ForegroundColor Yellow
} else {
    Write-Host "✓ .env file already exists" -ForegroundColor Green
}
Write-Host ""

# Step 3: Run setup verification
Write-Host "[3/4] Verifying installation..." -ForegroundColor Yellow
py test_setup.py
Write-Host ""

# Step 4: Instructions
Write-Host "[4/4] Next steps:" -ForegroundColor Yellow
Write-Host "  1. Edit .env with your Hyperliquid credentials"
Write-Host "  2. Run the bot with: " -NoNewline
Write-Host "py bot.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
Write-Host "Setup complete! Happy trading! 🚀" -ForegroundColor Green
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 79) -ForegroundColor Cyan
