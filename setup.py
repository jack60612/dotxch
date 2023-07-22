from setuptools import setup

dependencies = [
    "packaging",
    "chia-blockchain==1.8.2",
    "blspy",
    "click",
]

dev_dependencies = [
    "build",
    "coverage",
    "pre-commit",
    "pylint",
    "pytest",
    "pytest-asyncio",
    "isort",
    "flake8",
    "mypy",
    "black",
    "ipython",  # For asyncio debugging
    "pyinstaller",
    "types-aiofiles",
    "types-click",
    "types-cryptography",
    "types-pkg_resources",
    "types-pyyaml",
    "types-setuptools",
]


setup(
    name="dotxch",
    url="https://dotxch.io",
    license="Apache Licence",
    author="Jack Nelson",
    author_email="jack@jacknelson.xyz",
    description="dot-xch puzzles and tooling",
    python_requires=">=3.7, <4",
    keywords="xch dotxch chia domain",
    install_requires=dependencies,
    extras_require=dict(
        dev=dev_dependencies,
    ),
    packages=[
        "resolver",
        "resolver.api",
        "resolver.cmds",
        "resolver.core",
        "resolver.drivers",
        "resolver.puzzles",
        "resolver.types",
    ],
    entry_points={
        "console_scripts": [
            "resolver = resolver.cmds.resolver:resolver",
        ]
    },
    package_data={
        "": ["*.clvm", "*.clvm.hex", "*.clib", "*.clinc", "*.clsp", "py.typed"],
    },
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    project_urls={
        "Source": "https://github.com/jack60612/dotxch/",
        "Changelog": "https://github.com/jack60612/dotxch/blob/main/CHANGELOG.md",
    },
)
