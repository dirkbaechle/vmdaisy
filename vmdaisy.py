import os
import sys
import re
import time
import urllib2
import json
import subprocess
import shlex
import paramiko
import Queue

# Global dictionary with config values
config = None

def ssh_cmd(name, cmd):
    """ Tries to execute the given command cmd via SSH on the
        buildslave with the local config name.
    """
    global config
    slave = config['slaves'][name]
    removekey = config.get('removekey','')
    if removekey:
        # Try to call ssh-keygen to remove the possibly offending server key first
        rcmd = "%s %s" % (removekey, slave['sshserver'])
        subprocess.call(rcmd, shell=True) 
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(slave['sshserver'], 
                    username=slave['sshuser'], 
                    password=slave['sshpass'])
        print "ssh cmd: <%s>" % cmd
        ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(cmd)
        ssh.close()

        return True # success
    except:
        print "ssh cmd error!"

    return False


def shutdown_kvm(name):
    """ Shuts down the virtual machine for local buildslave name.
        Uses the command from the 'shutdown' key of the
        given slave's configuration, or '/sbin/shutdown now' as default.
    """
    global config
    slave = config['slaves'][name]
    shutdown = slave.get('shutdown','')
    if not shutdown:
        shutdown = 'sudo /sbin/shutdown now'

    return ssh_cmd(name, shutdown)

def start_kvm(name):
    """ Start the virtual machine for local buildslave name.
        The method assumes that it has been checked before, that
        the machine is not already running.
    """
    global config
    slave = config['slaves'][name]
    kvmopts = slave.get('kvmopts','')
    if not kvmopts:
        kvmopts = config['kvmopts']
    cmdline = "sudo kvm %s -hda %s" % (kvmopts, slave['kvmimg']) 
    cmds = shlex.split(cmdline)
    subprocess.Popen(cmds)
    
    return True

def shutdown_buildslave(name):
    """ Shuts down the buildslave process for local machine name.
        Uses the path from the 'slavedir' key of the
        given slave's configuration.
    """
    global config
    slave = config['slaves'][name]
    sdir = slave.get('slavedir','')
    if not sdir:
        sdir = '.'

    scmd = "buildslave stop %s" % sdir
    return ssh_cmd(name, scmd)

def start_buildslave(name):
    """ Starts the buildslave process for local machine name.
        Uses the path from the 'slavedir' key of the
        given slave's configuration.
    """
    global config
    slave = config['slaves'][name]
    sdir = slave.get('slavedir','')
    if not sdir:
        sdir = '.'

    scmd = "buildslave start %s" % sdir
    return ssh_cmd(name, scmd)

def get_processcmds():
    """ Return the list of currently running processes and their PIDs.
    """
    cmds = []
    pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]

    for pid in pids:
        try:
            cmd = open(os.path.join('/proc', pid, 'cmdline'), 'rb').read()
            cmds.append((cmd, pid))
        except IOError: # proc has already terminated
            continue
    return cmds

def get_running_kvms():
    """ Return the list of configured local slaves that are currently started
        in KVM, together with the PID of the process.
    """
    global config
    kvms = []
    cmds = get_processcmds()
    for c in cmds:
        cline = c[0].replace('\x00',' ')
        if cline.find('sudo kvm') >= 0 and cline.find(' -hda ') >= 0:
            # Found a kvm process, probably...
            qcow2 = re.search("\s+-hda\s+([^\s]+)", cline)
            if qcow2:
                started_img = qcow2.group(1)
                # Try to find image in list of configured slaves
                for name, vals in config['slaves'].iteritems():
                    img = vals.get('kvmimg','')
                    if img == started_img:
                        kvms.append((name, c[1]))
                        break

    return kvms

def vm_is_running(name):
    """ Return whether the VM for slave name is really running.
    """
    vms = get_running_kvms()
    found = False
    for v in vms:
        if v[0] == name:
            found = True
            break

    return found

def start(name):
    """ Combines the commands above for starting the VM and the buildslave,
        in order to graciously get the slave with the given local name
        online.
        Returns: True if successful, False in the case of an error (like
                 the VM didn't start, or similar)
    """
    print "Starting slave '%s'..." % name
    global config
    slave = config['slaves'][name]
    start_kvm(name)
    time.sleep(slave['startdelay'])
    # Ensure that VM is really running
    if not vm_is_running(name):
        print "  VM not active after initial wait! Aborting start..."
        return False

    start_buildslave(name)

    return True

def shutdown(name):
    """ Combines the commands above for stopping the VM and the buildslave,
        in order to graciously shutdown the slave with the given local name.
    """
    print "Shutting down slave '%s'..." % name
    global config
    slave = config['slaves'][name]
    shutdown_buildslave(name)
    time.sleep(config.get('bbdelay', 120))
    shutdown_kvm(name)
    time.sleep(slave['stopdelay'])
    # Ensure that VM is really stopped
    if vm_is_running(name):
        print "  VM still active after wait! Trying a direct kill..."
        subprocess.call("kill %s" % slave['kvmpid'])
        time.sleep(30)
        if vm_is_running(name):
            print "  No success!!! VM still active! Giving up..."
            return False

    return True

def poll_buildbot(server):
    """ Poll the given Buildbot server for the state of
        all the single slaves, and return a list of tuples
        with the basic infos we need: (name, state, #pendingBuilds).
    """
    states = []
    print "Polling buildbot server '%s' - %s" % (server, time.asctime())
    try:
        jsonfile = urllib2.urlopen("http://%s/json" % server)
        output = open('state.json','wb')
        output.write(jsonfile.read())
        output.close()
        # read slave states from JSON file
        with open("state.json") as json_file:
            json_data = json.load(json_file)
            builders = json_data.get('builders',[])
            for b, val in builders.iteritems():
                states.append((b, val.get('state','unknown'), val.get('pendingBuilds','0')))
    except:
        pass
    return states

def update_config(states):
    """ Update the global config with the given Buildbot states.
    """
    global config
    for s in states:
        # Try to find slave
        for c, vals in config['slaves'].iteritems():
            if vals.get('bbname','') == s[0]:
                # Found, now update values
                vals['bbstate'] = s[1]
                vals['lastpending'] = vals['bbpending']
                try:
                    vals['bbpending']  = int(s[2])
                except:
                    pass
                lasttime = vals.get('lasttime', 0)
                if lasttime == 0 or (vals['lastpending'] != vals['bbpending']):
                    vals['lasttime'] = time.time()
                break

def get_name_mappings():
    """ Return two maps, translating from remote->local and
        local->remote slave names.
    """
    global config
    local = {}
    remote = {}
    for c, vals in config['slaves'].iteritems():
        # Remote name on the BB server
        r = vals.get('bbname','')
        local[r] = c
        remote[c] = r

    return local, remote

def run():
    """ The main loop, which watches the Buildbot server's info and
        starts and stops the locally configured KVM machines on
        demand.
    """
    global config

    localname, remotename = get_name_mappings()
    vmq = Queue.Queue()
    current_vm = None
    states = poll_buildbot(config['bbserver'])
    while 1:
        #
        # Update our config['slaves'] info with the latest
        # state as found on the Buildbot server
        #
        update_config(states)

        #
        # Update list of currently active VMs, especially their PIDs
        #
        vms = get_running_kvms()
        if len(vms) == 0:
            current_vm = None
        elif len(vms) == 1:
            current_vm = vms[0][0]
            try:
                # Update PID, in case we have to kill the process later
                slave = config['slaves'].get(current_vm, None)
                if slave:
                    slave['kvmpid'] = vms[0][1]
            except:
                pass
        else:
            # Something's not right here...shutdown all
            print "Warning!!! More than one VM active at the same time!"
            print "           I'll shut down all active machines now..."
            for v in vms:
                shutdown(v[0])
            current_vm = None


        #
        # Decide basic run mode:
        # - if a VM is running currently, don't do
        #   anything, except checking whether it is still
        #   making some progress over time
        # - if no VM is started, check the queue
        #   * if there are entries in the queue, get the TOP and
        #     start to work through the queue
        #   * if the queue has no entries, check the pendingBuilds
        #     of all slaves, and if at least one slave is found
        #     push all pending slaves to the queue and
        #     start to work through them
        if current_vm:
            sd = False
            try:
                # Check the pending counter
                slave = config['slaves'].get(current_vm, None)
                if slave and slave['bbstate'] == 'idle' and slave['bbpending'] == 0:
                    sd = True # VM has finished its job...

                # Compare its lastpending time to current
                now = time.time()
                if (now - slave.get('lasttime', 0)) > 6*3600.0:
                    # VM seems to be hanging for more than 6 hours...
                    sd = True
            except:
                pass

            if sd:
                shutdown(current_vm) 
                current_vm = None
                if not vmq.empty():
                    # Try to start the next VM
                    while not vmq.empty():
                        nextvm = vmq.get()
                        if start(nextvm):
                            current_vm = nextvm
                            break

        else:
            # Are there any entries in the queue?
            if not vmq.empty():
                # Try to start the next VM
                while not vmq.empty():
                    nextvm = vmq.get()
                    if start(nextvm):
                        current_vm = nextvm
                        break
            else:
                for name, vals in config['slaves'].iteritems():
                    # If a local slave has pending builds
                    if vals.get('bbpending', 0) > 0:
                        # Add it to the queue
                        vmq.put(name)

                # Are there any entries in the queue?
                if not vmq.empty():
                    # Try to start the next VM
                    while not vmq.empty():
                        nextvm = vmq.get()
                        if start(nextvm):
                            current_vm = nextvm
                            break

        time.sleep(config['idlepoll'])
        states = poll_buildbot(config['bbserver'])

def read_config(fpath):
    """ Read the configuration, especially the list of local
        KVM machines and their settings, from the given JSON file.
    """
    global config

    try:
        # read config from JSON file
        with open(fpath) as json_file:
            config = json.load(json_file)

        return True
    except:
        pass

    return False

# Mapping from command line keywords to function names
run_method = {"kvmup": start_kvm,
              "kvmdown": shutdown_kvm,
              "bbup": start_buildslave,
              "bbdown": shutdown_buildslave}

def usage():
    print "VMDaisy - db, 2018-09-22"
    print "Usage: vmdaisy <config.json> [info|state|kvmup *|kvmdown *|bbup *|bbdown *]"
    
def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(0)

    # Read config file
    if not read_config(sys.argv[1]):
        print "Error while reading config!"

    if len(sys.argv) == 2:
        # Start the ring...
        run()
        return

    # Testing options
    if sys.argv[2] == "info":
        print "Slaves:"
        for name in config['slaves']:
            print "  %s" % name
        print "\nCurrently active:"
        kvmlist = get_running_kvms()
        if kvmlist:
            for k in kvmlist:
                print "  %s (%s)" % (k[0], k[1])
        else:
            print "  None"
        print ""
        return
    elif sys.argv[2] == "state":
        states = poll_buildbot(config['bbserver'])
        update_config(states)
        print "Slaves:"
        for name,c in config['slaves'].iteritems():
            print "  %s" % name
            print "    bbname:  %s" % c.get('bbname','')
            print "    bbstate: %s" % c['bbstate']
            print "    pending: %d" % c['bbpending']
        return

    if len(sys.argv) > 3:
        name = sys.argv[3]
        if name not in config['slaves']:
            print "Invalid name '%s'!" % name
            return
        print run_method[sys.argv[2]](name)

if __name__ == "__main__":
    main()
