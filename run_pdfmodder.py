"""Punto de entrada Windows (también usado por PyInstaller)."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from pdfmodder.app import main
    raise SystemExit(main())
