from setuptools import setup, find_packages

setup(
    name="queuectl",
    version="1.0.0",
    description="CLI-based background job queue system with retry, DLQ, and persistent storage",
    author="QueueCTL",
    packages=find_packages(),
    install_requires=[
        "click>=8.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-timeout>=2.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "queuectl=queuectl.cli:cli",
        ],
    },
    python_requires=">=3.8",
)