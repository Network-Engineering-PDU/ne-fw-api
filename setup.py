import re
import setuptools

with open("ttne/config.py") as f:
    version = re.search(r"VERSION = \"(.*?)\"", f.read()).group(1)

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="ttne",
    version=version,
    author="Tychetools",
    description="Tychetools application for Network Engineering",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://bitbucket.org/tychetools/ne-fw-api/src/master/",
    packages=setuptools.find_packages(),
    package_data={
        "ttne": ["model_data/*"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
    ],
    python_requires=">=3.7",
    install_requires=[
        "requests==2.28.1",
        "fastapi==0.89.0",
        "uvicorn[standard]==0.20.0",
        "python-multipart==0.0.5",
        "packaging==21.3", # No sé como va lo de las versiones
        "pyserial==3.5", # No sé como va lo de las versiones
        "smbus2==0.3.0", # No sé como va lo de las versiones
    ],
    entry_points={
        "console_scripts": {
            "ttnedaemon = ttne.__init__:daemon",
        }
    },
    scripts=[
        "scripts/ttnelog"
    ]
)
