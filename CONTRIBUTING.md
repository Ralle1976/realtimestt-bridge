# Contributing to RealtimeSTT Bridge Plugin

Thank you for considering contributing to the RealtimeSTT Bridge Plugin!

## How to Contribute

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes**
4. **Test thoroughly**
5. **Commit your changes**: `git commit -m 'Add amazing feature'`
6. **Push to the branch**: `git push origin feature/amazing-feature`
7. **Open a Pull Request**

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/realtimestt-bridge.git
cd realtimestt-bridge

# Install dependencies
pip install RealtimeSTT

# On Linux, also install:
sudo apt-get install python3-dev portaudio19-dev
```

## Testing

Test all three commands:

```bash
# Test one-shot recognition
/stt-once { "language": "de" }

# Test continuous mode
/stt-arm { "language": "de" }
# Speak: "CLAUDE schreibe test"
# Speak: "CLAUDE stop"
/stt-disarm {}
```

## Code Style

- Python code follows PEP 8
- JavaScript/Node.js code uses CommonJS modules
- Clear, descriptive variable names
- Comments for complex logic

## Reporting Bugs

Please open an issue with:
- Clear description of the bug
- Steps to reproduce
- Expected vs actual behavior
- System information (OS, Python version, Node.js version)

## Feature Requests

Open an issue describing:
- The problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered

## Questions?

Open an issue with the "question" label.

Thank you for contributing!
