# GENFORGE Fonts

## Self-Hosted Fonts

This directory contains self-hosted font files for GENFORGE to eliminate external dependencies.

### Required Fonts

**Inter** (Variable)
- Download from: https://github.com/rsms/inter/releases
- Files needed: Inter-VariableFont_slnt,wght.ttf or InterVariable.woff2
- License: SIL Open Font License

**Space Grotesk** (Variable or Regular/Bold)
- Download from: https://fonts.google.com/specimen/Space+Grotesk
- Files needed: SpaceGrotesk-VariableFont_wght.ttf or individual weights
- License: SIL Open Font License

**JetBrains Mono** (Variable or Regular/Bold)
- Download from: https://www.jetbrains.com/lp/mono/
- Files needed: JetBrainsMono[wght].ttf or individual weights
- License: Apache 2.0

### Installation Instructions

1. Download the fonts from the links above
2. Place the font files in this directory
3. The application will automatically use them via @font-face declarations

### Fallback Behavior

If fonts are not present, the application will fallback to:
- Inter → -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif
- Space Grotesk → Inter, sans-serif
- JetBrains Mono → 'Cascadia Code', 'Fira Code', Consolas, monospace

The application will render correctly even without self-hosted fonts.
