import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pootle_utils-Pootle", # Replace with your own username
    version="0.1",
    author="Iain Malcolm",
    author_email="iainmalcolm1@gmail.com",
    description="stuff I use in various other packages",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pootle/pootles_utils",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Universal Permissive License (UPL)",
        "Operating System :: POSIX :: Linux",
    ],
    python_requires='>=3.5',
)