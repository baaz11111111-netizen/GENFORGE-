# GENFORGE

**AI-Powered Media Studio for Autonomous Content Creation**

GENFORGE is a Streamlit-based application that combines FFmpeg editing pipelines, AI-powered content generation, and multi-platform publishing into a unified studio for creating social media content at scale.

---

## Features

### Core Capabilities
- **Video Studio**: Timeline-based video editor with trim, split, transitions, audio mixing
- **Image Studio**: AI-powered background removal, compositing, gradient backgrounds
- **Script Studio**: AI script generation with hooks, CTAs, and variations
- **Campaign Hub**: Multi-platform campaign planning with content calendars
- **Audio Tools**: Noise reduction, EQ presets, dynamics processing, waveform visualization
- **Publishing**: Multi-platform publishing with TikTok, Instagram, YouTube, LinkedIn support
- **Highlights**: Automated highlight detection and platform-specific exports
- **AI Director**: Automated editing suggestions based on content analysis

### Technical Stack
- **Frontend**: Streamlit with custom timeline component (HTML/JavaScript)
- **Media Processing**: FFmpeg for video/audio encoding and manipulation
- **AI Integration**: Google Gemini for script generation, image analysis, content recommendations
- **Image Processing**: PIL/Pillow, OpenCV (cv2), rembg for background removal
- **Storage**: JSON-based project persistence with file-based media assets

---

## Quick Start

### Prerequisites
- Python 3.11 or 3.12
- FFmpeg and ffprobe (must be on PATH)
- Google Gemini API key

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd GENFORGE
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   
   # Windows
   .venv\Scripts\Activate.ps1
   
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   
   Copy `.env.example` to `.env` and add your API keys:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and set:
   ```
   GEMINI_API_KEY=your_actual_gemini_api_key_here
   ```

5. **Run the application**
   ```bash
   python -m streamlit run app.py
   ```
   
   Or use the convenience script:
   ```bash
   python run_app.py
   ```

The application will open in your browser at `http://localhost:8501`

---

## Testing

### Run Fast Test Suite
```bash
pytest tests/ -m "not slow" -v
```

### Run Full Test Suite (including FFmpeg-intensive tests)
```bash
pytest tests/ -v
```

**Note:** Full test suite includes ~150 slow integration/E2E tests that perform real video encoding and may take 10+ minutes to complete.

### Test Organization
- **Unit tests**: Fast, isolated service-level tests (~970 tests)
- **Integration tests**: Multi-service workflows with real FFmpeg (~70 tests)
- **E2E tests**: Complete user workflows from UI to published output (~50 tests)
- **Slow tests**: FFmpeg-intensive transition/rendering tests (~50 tests)

### Current Test Status
- **Total tests**: 1,127 collected
- **Fast suite**: ~970 tests pass in < 2 minutes
- **Coverage**: Manual verification shows core services well-covered; automated coverage reporting pending

See `PRODUCTION_AUDIT_FINDINGS.md` for detailed test analysis.

---

## Project Structure

```
GENFORGE/
├── app.py                      # Main Streamlit application (3,401 lines - refactoring needed)
├── services/                   # Core business logic (well-architected)
│   ├── project_model.py        # Project state and persistence models
│   ├── project_store.py        # Project storage abstraction
│   ├── media_probe.py          # FFmpeg metadata extraction
│   ├── highlights.py           # AI highlight detection
│   ├── publishing/             # Multi-platform publishing abstraction
│   └── ...
├── components/                 # Custom Streamlit components
│   └── timeline/               # Timeline editor component
├── tests/                      # Comprehensive test suite (1,127 tests)
├── benchmarks/                 # Performance benchmarking suite
├── docs/                       # Documentation (see docs/index.md)
├── .env                        # Environment variables (not in git)
├── .env.example                # Environment template
├── requirements.txt            # Pinned dependencies
├── requirements-lock.txt       # Full dependency lockfile (151 packages)
└── pytest.ini                  # Test configuration
```

---

## Architecture

### Services Layer
The `services/` directory contains the core business logic, isolated from UI concerns:
- **Project Management**: State management, persistence, versioning
- **Media Pipeline**: Probe, trim, encode, normalize, export
- **Audio Pipeline**: Waveform analysis, noise reduction, mixing
- **Publishing**: Platform abstraction with mock/real providers
- **Performance**: Metrics collection and analysis
- **AI Integration**: Gemini API abstraction for content generation

See `docs/ARCHITECTURE.md` for detailed architecture documentation.

### Timeline Component
Custom Streamlit component built with HTML/JavaScript for professional video editing:
- Pixel-to-time coordinate conversions with zoom support
- Drag-and-drop clip reordering
- Snap-to-grid for precise edits
- Waveform visualization
- Undo/redo with deep-copy state management

See `docs/TIMELINE_IMPLEMENTATION.md` for implementation details.

---

## Documentation

All documentation is organized in the `docs/` directory:

- **[docs/index.md](docs/index.md)** - Complete documentation index
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System architecture
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** - Production deployment guide
- **[docs/AGENTS.md](docs/AGENTS.md)** - AI agent system
- **[PRODUCTION_AUDIT_FINDINGS.md](PRODUCTION_AUDIT_FINDINGS.md)** - Independent audit results

---

## Production Readiness

### Completed
✅ **Security**: Exposed API keys neutralized, `.env` protected, secret scan clean  
✅ **Dependencies**: All 19 dependencies pinned to exact versions, lockfile generated  
✅ **Bug Fixes**: 3 P2/P3 bugs fixed with regression tests (timeline undo, mock failures, whitespace IDs)  
✅ **Testing**: 1,127 tests with fast/slow separation, representative subsets passing  
✅ **Documentation**: Consolidated into `docs/` with index and corrected QA report  

### Pending
⚠️ **Code Organization**: `app.py` is 3,401 lines - needs refactoring into modules (deferred for dedicated session)  
⚠️ **Test Coverage**: Automated coverage reporting not working (pytest-cov issue) - manual verification only  
⚠️ **Clean Install**: Fresh venv install test not performed  

### Known Gaps
- `run_autonomous_campaign` has no test coverage (actively used in Campaign Swarm)
- Real platform OAuth flows require manual testing with live credentials
- Full test suite times out on some environments (FFmpeg-intensive tests)

See `PRODUCTION_AUDIT_FINDINGS.md` for complete audit details.

---

## Known Issues

1. **Test suite timeout**: Full suite with slow FFmpeg tests can exceed 5 minutes. Use `-m "not slow"` for fast development feedback.
2. **pytest-cov not working**: Coverage reporting unavailable despite plugin installation. Manual test counting used.
3. **app.py monolith**: Main file is too large (3,401 lines). Refactoring to `pages/` modules recommended.

---

## Contributing

1. **Before making changes**: Read `PRODUCTION_AUDIT_FINDINGS.md` for current system status
2. **Run tests**: Always run at least the fast test suite before committing
3. **Follow patterns**: Study `services/` architecture - new features should follow this isolation pattern
4. **Document**: Update relevant docs in `docs/` directory

---

## Security

- **API keys**: Never commit `.env` file (already in `.gitignore`)
- **Rotate keys**: If this repo was ever public, rotate all API keys in `.env`
- **Secret scanning**: Re-run secret scan after adding new configuration files

---

## License

*(Add your license here)*

---

## Support

For issues or questions:
1. Check `PRODUCTION_AUDIT_FINDINGS.md` for known issues
2. Review `docs/` for implementation details
3. Run test suite to verify your environment

---

**Last Updated**: September 6, 2026 (Production Audit)
