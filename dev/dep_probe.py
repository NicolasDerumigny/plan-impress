#!/usr/bin/env python3
"""Isolate why unopkg reports "unsatisfied dependencies" for a dependency block.

Builds a minimal package (manifest + description only) for each description.xml
variant and installs it into a throwaway profile, printing the outcome.

    python3 dev/dep_probe.py
"""
import os
import shutil
import subprocess
import zipfile

WORK = "/tmp/opencode/depprobe"
IDENTIFIER = "org.nicolasderumigny.depprobe"

VARIANTS = {
    "none": "",
    "lo-ns-correct": '''
    <dependencies>
        <lo:LibreOffice-minimal-version value="7.0" d:name="LibreOffice 7.0"/>
    </dependencies>''',
    "lo-ns-correct-26.8": '''
    <dependencies>
        <lo:LibreOffice-minimal-version value="26.8" d:name="LibreOffice 26.8"/>
    </dependencies>''',
    "lo-ns-correct-99": '''
    <dependencies>
        <lo:LibreOffice-minimal-version value="99.0" d:name="LibreOffice 99"/>
    </dependencies>''',
    "both": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="4.1" d:name="OpenOffice.org 4.1"/>
        <lo:LibreOffice-minimal-version value="7.0" d:name="LibreOffice 7.0"/>
    </dependencies>''',
    "ooo4.1": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="4.1" d:name="OOO 4.1"/>
    </dependencies>''',
    "ooo4.2": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="4.2" d:name="OOO 4.2"/>
    </dependencies>''',
    "ooo0": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="0.0" d:name="OOO 0.0"/>
    </dependencies>''',
    "ooo1": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="1.0" d:name="OOO 1.0"/>
    </dependencies>''',
    "ooo2": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="2.0" d:name="OOO 2.0"/>
    </dependencies>''',
    "ooo2.9": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="2.9" d:name="OOO 2.9"/>
    </dependencies>''',
    "ooo3.1": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="3.1" d:name="OOO 3.1"/>
    </dependencies>''',
    "ooo4": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="4.0" d:name="OOO 4.0"/>
    </dependencies>''',
    "lo2": '''
    <dependencies>
        <LibreOffice-minimal-version value="2.0" d:name="LO 2.0"/>
    </dependencies>''',
    "lo26": '''
    <dependencies>
        <LibreOffice-minimal-version value="26.8" d:name="LO 26.8"/>
    </dependencies>''',
    "ooo3-root-ns": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="3.0" d:name="OpenOffice.org 3.0"/>
    </dependencies>''',
    "ooo3-el-ns": '''
    <dependencies>
        <OpenOffice.org-minimal-version xmlns:d="http://openoffice.org/extensions/description/2006"
            value="3.0" d:name="OpenOffice.org 3.0"/>
    </dependencies>''',
    "ooo7": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="7.0" d:name="LibreOffice 7.0"/>
    </dependencies>''',
    "lo7": '''
    <dependencies>
        <LibreOffice-minimal-version value="7.0" d:name="LibreOffice 7.0"/>
    </dependencies>''',
    "lo7-no-name-attr": '''
    <dependencies>
        <LibreOffice-minimal-version value="7.0"/>
    </dependencies>''',
    "extension": '''
    <dependencies>
        <OpenOffice.org-minimal-version value="3.0" d:name="OpenOffice.org 3.0"/>
        <LibreOffice-minimal-version value="7.0" d:name="LibreOffice 7.0"/>
    </dependencies>''',
}

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<description xmlns="http://openoffice.org/extensions/description/2006"
             xmlns:d="http://openoffice.org/extensions/description/2006"
             xmlns:lo="http://libreoffice.org/extensions/description/2011"
             xmlns:xlink="http://www.w3.org/1999/xlink">
    <version value="1.0.0"/>
    <identifier value="%s"/>
    <display-name><name lang="en-US">Dep Probe</name></display-name>%s
</description>
"""

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="http://openoffice.org/2001/manifest">
    <manifest:file-entry manifest:full-path="readme.txt"
                         manifest:media-type="application/vnd.sun.star.package-bundle-description"/>
</manifest:manifest>
"""


def build(name, body, path):
    folder = os.path.join(WORK, name)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(os.path.join(folder, "META-INF"))
    with open(os.path.join(folder, "description.xml"), "w") as handle:
        handle.write(TEMPLATE % (IDENTIFIER, body))
    with open(os.path.join(folder, "META-INF", "manifest.xml"), "w") as handle:
        handle.write(MANIFEST)
    with open(os.path.join(folder, "readme.txt"), "w") as handle:
        handle.write("dep probe\n")
    if os.path.exists(path):
        os.remove(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, _dirs, files in os.walk(folder):
            for filename in files:
                full = os.path.join(root, filename)
                archive.write(full, os.path.relpath(full, folder))


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    for index, (name, body) in enumerate(VARIANTS.items()):
        profile = os.path.join(WORK, "profile-%d" % index)
        oxt = os.path.join(WORK, "%s.oxt" % name)
        build(name, body, oxt)
        subprocess.run(["unopkg", "-env:UserInstallation=file://" + profile, "remove",
                        IDENTIFIER], capture_output=True, timeout=120)
        result = subprocess.run(["unopkg", "-env:UserInstallation=file://" + profile,
                                 "add", oxt], capture_output=True, text=True, timeout=180)
        outcome = (result.stdout + result.stderr).strip().replace("\n", " ")
        print("%-22s exit=%d %s" % (name, result.returncode, outcome[:110] or "ok"))


if __name__ == "__main__":
    main()
