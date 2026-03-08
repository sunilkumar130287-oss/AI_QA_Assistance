"""Package setup for agent-framework."""

from setuptools import setup, find_packages

setup(
    name="agent-framework",
    version="0.1.0",
    description="Enterprise-grade autonomous AI coding agent framework",
    author="Agent Framework Team",
    python_requires=">=3.11",
    packages=find_packages(exclude=["tests*"]),
    install_requires=[
        "requests>=2.31.0,<3.0",
        "pyyaml>=6.0,<7.0",
        "python-dotenv>=1.0.0,<2.0",
        "tenacity>=8.2.0,<9.0",
        "rich>=13.0.0,<14.0",
        "networkx>=3.1,<4.0",
        "gitpython>=3.1.40,<4.0",
        "tree-sitter>=0.21.0,<1.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0,<9.0",
            "pytest-cov>=4.1.0,<6.0",
            "pytest-mock>=3.11.0,<4.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "agent-framework=main:main",
        ],
    },
)
