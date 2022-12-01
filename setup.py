from setuptools import setup

dependencies = [
    "chia-blockchain==1.6.1",
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
    # TODO: black 22.1.0 requires click>=8, remove this pin after updating to click 8
    "black==21.12b0",
    "aiohttp_cors",  # For blackd
    "ipython",  # For asyncio debugging
    "pyinstaller==5.0",
    "types-aiofiles",
    "types-click",
    "types-cryptography",
    "types-pkg_resources",
    "types-pyyaml",
    "types-setuptools",
]


setup(
    name="dotxch",
    version="0.0.1",
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
        "resolver.cmds",
        "resolver.puzzles",
    ],
    entry_points={
        "console_scripts": [
            "resolver = resolver.cmds.resolver:main",
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
