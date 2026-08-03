# R Workshop Installation Guide
## R, RStudio, and Required Packages

**Workshop Series**

Understanding Biological Data Through R
Balik Scientist Program · Mariano Marcos State University
Programme Lead: Dr. Imelda L. Forteza

**Document Owner**

Jan Ephraim R. Vallente
Research Assistant

---

# Purpose

This document provides the installation instructions required before attending the R Workshop.

Participants are encouraged to complete all software installation and package installation **before the workshop**. Completing these steps in advance allows the workshop to focus on data analysis rather than software configuration.

This guide assumes little to no previous experience with R.

---

# Software Required

Every participant should install the following software.

| Software | Purpose |
|-----------|---------|
| R | Statistical computing language |
| RStudio Desktop | Integrated Development Environment (IDE) for R |

> **Important**
>
> R and RStudio are **different software**.
>
> **R must be installed first.**
>
> RStudio should be installed afterwards because it uses the R installation already present on the computer.

---

# Part I — Installing R

## Windows

1. Visit the official CRAN website.

   https://cran.r-project.org/

2. Select

   **Download R for Windows**

3. Select

   **base**

4. Download the latest installer.

5. Run the installer.

6. The default installation options are appropriate for nearly all participants.

---

## macOS

1. Visit

   https://cran.r-project.org/

2. Select

   **Download R for macOS**

3. Download the installer appropriate for the computer.

   - Apple Silicon (M-series)
   - Intel

4. Run the installer.

5. Accept the default installation options.

---

# Part II — Installing RStudio Desktop

After R has been installed successfully,

1. Visit

   https://posit.co/download/rstudio-desktop/

2. Download the latest free version of **RStudio Desktop**.

3. Run the installer.

4. Accept the default installation settings.

When RStudio is opened for the first time, it should automatically detect the installed version of R. 

---

# Part III — Verify the Installation

Open RStudio.

In the Console, type

```r
R.version.string
```

Example

```text
[1] "R version 4.6.1 (2026-06-24)"
```

Additional information may be displayed using

```r
sessionInfo()
```

---

# Part IV — Install the Required Packages

The workshop requires the following CRAN packages.

```r
install.packages(c(
    "readr",
    "dplyr",
    "ape",
    "ggplot2"
))
```

---

# Install BiocManager

```r
install.packages("BiocManager")
```

`BiocManager` is the official package manager for installing Bioconductor packages. 

---

# Install phyloseq

```r
BiocManager::install("phyloseq")
```

`phyloseq` is distributed through Bioconductor rather than CRAN.

---

# Verify Package Installation

Run

```r
library(readr)
library(dplyr)
library(ape)
library(ggplot2)
library(phyloseq)
```

If no error messages are produced, the installation was successful.

---

# Common Questions

## "Do you want to install from sources the package which needs compilation?"

Some participants—particularly those using a newly released version of R—may encounter the following prompt.

```text
Do you want to install from sources the package which needs compilation?
(Yes/no/cancel)
```

For this workshop, the recommended response is

> **No**

Selecting **No** instructs R to install precompiled binary packages whenever they are available.

Selecting **Yes** may require additional development tools, such as

- Rtools (Windows)
- Xcode Command Line Tools (macOS)

Unless specifically instructed by the workshop facilitators, participants should choose **No**. 

---

## Bioconductor May Request Package Updates

During installation, R may pause and display a message similar to

```text
Old packages: 'MASS', 'nlme', 'survival'
Update all/some/none? [a/s/n]: 
```

This is a **question awaiting a single letter**, not a prompt for an R command. The
notation `[a/s/n]` lists the only three valid answers:

| Answer | Meaning |
|--------|---------|
| `a` | update all |
| `s` | choose individually |
| `n` | update none |

For this workshop, type

> **`n`**

and press Enter.

The packages listed are R's *recommended* packages, which are installed together with R
itself. On Windows they reside in a protected folder (`C:/Program Files/...`), and an
ordinary user account cannot modify them. Attempting to update them therefore produces
the following, which participants may see:

```text
Installation paths not writeable, unable to update packages
  path: C:/Program Files/R/R-4.6.1/library
  packages: boot, class, cluster, KernSmooth, lattice, MASS, Matrix,
            mgcv, nlme, nnet, rpart, spatial, survival
```

**This message is a warning, not a failure.** The package that was requested installs
successfully regardless; only the protected recommended packages are left untouched.
Answering `n` avoids the situation altogether. These packages do not require updating for
this workshop, and RStudio should **not** be run as an administrator in order to update
them.

---

## Package Installation Appears Slow

Package installation depends upon

- internet speed;
- CRAN mirror availability;
- package size.

Some packages, particularly Bioconductor packages, may require several minutes to install.

This behaviour is normal.

---

## Compilation Messages

During installation, numerous messages may appear in the Console.

This behaviour is expected.

Participants should wait until the Console prompt (`>`) returns before entering additional commands.

---

## Package Already Installed

Running

```r
install.packages(...)
```

again is safe.

R checks whether newer versions are available before installation.

---

## Installing Does Not Automatically Load a Package

Installing a package and loading a package are separate operations.

Packages must be loaded each time a new R session begins.

Example

```r
library(readr)
```

---

## Administrative Permissions

On institutional or laboratory computers, software installation may require administrative privileges.

If installation fails because of insufficient permissions, participants should contact the workshop organisers.

---

# Recommended Preparation

Participants are encouraged to

- complete all installations before the workshop;
- verify that RStudio opens successfully;
- verify that every required package loads correctly;
- maintain a stable internet connection during package installation;
- avoid reinstalling R immediately before the workshop unless instructed.

---

# Helpful Commands

Display the installed R version

```r
R.version.string
```

Display detailed session information

```r
sessionInfo()
```

Display the installed version of a package

```r
packageVersion("phyloseq")
```

Display package documentation

```r
help(package = "phyloseq")
```

---

# Verification Record

| Item | Status | Source |
|------|--------|--------|
| R installed before RStudio | Verified | CRAN / Posit |
| RStudio installation procedure | Verified | Posit Documentation |
| CRAN package installation | Verified | CRAN / BiocManager documentation |
| BiocManager installation | Verified | Official BiocManager documentation |
| phyloseq installation command | Verified | Official Bioconductor package page |
| Verification commands (`R.version.string`, `sessionInfo()`) | Verified | Standard R installation workflow |

---

# Revision Record

| Version | Date | Change |
|---------|------|--------|
| 1.0 | [date of initial issue] | Initial issue, prior to Session 1. |
| 1.1 | 24 July 2026 | Guidance on the package-update prompt corrected: `n` recommended in place of "Yes". Explanation of the "Installation paths not writeable" warning added. Attribution block added. |