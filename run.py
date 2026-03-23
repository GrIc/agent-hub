#!/usr/bin/env python3
"""Shortcut: python run.py"""
import sys
import traceback

try:
    from src.main import main
    main()
except SystemExit as e:
    sys.exit(e.code)
except KeyboardInterrupt:
    print("\nInterrupted.")
except Exception as e:
    print(f"\n{'='*60}")
    print(f"CRASH: {type(e).__name__}: {e}")
    print(f"{'='*60}")
    traceback.print_exc()
    print(f"\nIf the error involves ChromaDB:")
    print(f"  python run.py --clean")
    input("\nPress Enter to quit...")
    sys.exit(1)
