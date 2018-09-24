VMDaisy
=======

This tool is currently used for providing part of the
CI for the build system SCons, mainly running the test suite on
several OS VMs.

In a loop, the Buildbot server is polled for pending commits. If
new commits are signaled, "vmdaisy" will launch all configured VMs in
a row. Within each VM the SCons test suite is run by starting the
configured Buildbot slave. Afterwards, the VM is shutdown again and
the next one in the queue is picked.

