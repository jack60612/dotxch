from setuptools import setup
dependencies = [
    "chia-blockchain==1.5.0",
]



setup(
    name='dotxch',
    version='0.0.1',
    url='https://dotxch.io',
    license='Apache Licence',
    author='Jack Nelson',
    author_email='jack@jacknelson.xyz',
    description='dot-xch puzzles and tooling',
    python_requires=">=3.7, <4",
    keywords="xch dotxch chia domain",
    install_requires=dependencies,
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
