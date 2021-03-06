# -*- coding: utf-8 -*-
"""Classes used in loon package"""

import sys
import os
import json
import socket
import glob
import re
import io
from getpass import getpass
from subprocess import run, PIPE
from datetime import datetime
from shutil import copyfile
from ssh2.session import Session
if __package__ == '' or __package__ is None:    # Use for test
    from __init__ import __host_file__
    from utils import create_parentdir, isfile, isdir, pretty_table, get_filelist, read_csv
else:
    from loon import __host_file__
    from loon.utils import create_parentdir, isfile, isdir, pretty_table, get_filelist, read_csv

this_file = os.path.realpath(__file__)
this_dir = os.path.dirname(this_file)
data_dir = os.path.join(this_dir, 'data')


class Host:
    """
    Representation of remote host
    """
    def __init__(self, hostfile=__host_file__):
        self.hostfile = hostfile
        self.load_hosts()
        return

    def load_hosts(self):
        """Load hosts from file"""
        if not isfile(self.hostfile):
            self.active_host = []
            self.available_hosts = []
        else:
            with open(self.hostfile, 'r') as f:
                hosts = json.load(f)
            self.active_host = hosts['active']
            self.available_hosts = hosts['available']

        if any(isinstance(i, list) for i in self.active_host):
            print(
                "Error: more than one active host. Please check config file ~/.config/loon/host.json and modify or remove it if necessary."
            )

        # Python code to remove duplicate elements
        def RemoveDups(duplicate):
            final_list = []
            flag = False
            for num in duplicate:
                if num not in final_list:
                    final_list.append(num)
                else:
                    flag = True
            return final_list, flag

        self.available_hosts, flag = RemoveDups(self.available_hosts)

        if flag:
            # Save unique hosts immediately
            self.save_hosts()

        return

    def save_hosts(self):
        """Save hosts to file"""
        # if len(self.active_host)==0 or len(self.available_hosts)==0:
        #     raise ValueError("Cannot save to file due to null host.")
        hosts = {'active': self.active_host, 'available': self.available_hosts}
        if not isfile(self.hostfile):
            # Create parent dir if hostfile does not exist
            create_parentdir(self.hostfile)
        with open(self.hostfile, 'w') as f:
            json.dump(hosts, f)
        return

    def add(self, name, username, host, port=22, dry_run=False):
        """Add a remote host
        
        Args:
            name: hostname alias, a string
            username: hostname, a string
            host: host ip address, a string
            port: host ip port, an integer
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        info = [name, username, host, port]

        if dry_run:
            print("=> Running add", tuple(info[1:]))
            sys.exit(0)

        if info in self.available_hosts:
            print("=> Input host exists. Will not change.")
            return
        else:
            self.available_hosts.append(info)
            if len(self.active_host) == 0:
                self.active_host = info
            self.save_hosts()
            print("=> Added successfully!")
        return

    def host_check(self, name, username, host, port=22):
        """Check if a host exists

        Args:
            name: hostname alias, a string
            username: hostname, a string
            host: host ip address, a string
            port: host ip port, an integer
        
        Returns:
            a list representing the host
        """
        host = []
        if name is not None:
            for h in self.available_hosts:
                if h[0] == name:
                    host = h.copy()
        else:
            info = [username, host, port]
            for h in self.available_hosts:
                if h[1:] == info:
                    host = h.copy()
        if len(host) == 0:
            print(
                "=> Host does not exist, please check input with list command!"
            )
            sys.exit(1)
        return host

    def delete(self, name, username, host, port=22, dry_run=False):
        """Delete a remote host
        
        Args:
            name: hostname alias, a string
            username: hostname, a string
            host: host ip address, a string
            port: host ip port, an integer
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        if dry_run:
            print("Running delete", (username, host, port))
            sys.exit(0)
        host2del = self.host_check(name, username, host, port)
        print("=> Removing host from available list...")
        self.available_hosts.remove(host2del)
        if host2del == self.active_host:
            print("=> Removing active host...")
            if len(self.available_hosts) > 0:
                self.active_host = self.available_hosts[0]
                print("=> Changing active host to %s" % self.active_host[0])
            else:
                self.active_host = []    # reset
                print("=> Reseting active host to []")
        self.save_hosts()
        return

    def switch(self, name, username, host, port=22, dry_run=False):
        """Switch active host
        
        Args:
            name: hostname alias, a string
            username: hostname, a string
            host: host ip address, a string
            port: host ip port, an integer
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        if dry_run:
            print("Running switch",
                  (username, host, port) if username is not None else name)
            sys.exit(0)
        host2switch = self.host_check(name, username, host, port)
        self.active_host = host2switch
        self.save_hosts()
        print("=> %s activated." % name)
        return

    def rename(self, old, new, dry_run=False):
        """Rename host name
        
        Args: 
            old: a string representing the old host name alias
            new: a string representing the new host name alias
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        if dry_run:
            print("Running rename", old, "to", new)
            sys.exit(0)
        host2rename = []
        for index, h in enumerate(self.available_hosts):
            if h[0] == old:
                host2rename = h.copy()
                self.available_hosts[index][0] = new
        if len(host2rename) == 0:
            print(
                "=> Host does not exist, please check input with list command!"
            )
            sys.exit(1)
        if host2rename == self.active_host:
            self.active_host[0] = new
        self.save_hosts()
        return

    def list(self):
        """List all remote hosts"""

        title = ['Alias', 'Username', 'IP address', 'Port']
        content = self.available_hosts.copy()
        for host in content:
            if host == self.active_host:
                host[0] = '<' + host[0] + '>'
        pretty_table(title, content)
        print("<active host>")
        return

    def connect(self,
                privatekey_file="~/.ssh/id_rsa",
                passphrase='',
                open_channel=True):
        """Connect active host and open a session
        
        Args:
            privatekey_file: a string representing the path to the private key file
            passphrase: a string representing the password
            open_channel: if `True`, open the SSH channel

        Returns:
            None
        """
        privatekey_file = os.path.expanduser(privatekey_file)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.active_host[2], self.active_host[3]))
        s = Session()
        s.handshake(sock)
        try:
            # Try using private key file first
            s.userauth_publickey_fromfile(self.active_host[1], privatekey_file,
                                          passphrase)
        except:
            # Use password to auth
            passwd = getpass(
                'No private key found.\nEnter your password for %s: ' %
                self.active_host[1])
            s.userauth_password(self.active_host[1], passwd)
        self.session = s
        if open_channel:
            self.channel = self.session.open_session()
        return

    def cmd(self,
            commands,
            _logger=None,
            run_file=False,
            data_dir=None,
            remote_file=False,
            dir='/tmp',
            prog=None,
            dry_run=False):
        """Run command(s) in active remote host using channel session
        Therefore, `open_channel` in `connect` method must be `True` before using it.

        Args:
            commands: commands/scripts run on active remote host
            _logger: the logging logger
            run_file: if `True`, run scripts instead of commands
            data_dir: a path representing data directory
            remote_file: if `True`, collect input from remote host instead of local machine
            dir: Remote directory for storing local scripts
            prog: a string representing the program to run the commands
            dry_run: if `True`, dry run the code

        Returns:
            A string containing result information
        """
        if dry_run:
            print("Running", "files:" if run_file else "commands:", commands)
            sys.exit(0)
        if not run_file:
            self.connect()
            self.channel.execute(commands)
        else:
            # Run scripts
            _logger.info(commands)
            scripts = commands
            # commands are scripts here
            if remote_file:
                # Run remote scripts
                # Support some wildcards
                # *,?,{}
                wildcards = r'\*|\?|\{\}'
                matches = [
                    re.compile(wildcards).search(i) is not None
                    for i in scripts
                ]
                if any(matches):
                    commands_1 = list(map(lambda x: 'ls ' + x, scripts))
                    commands_1 = ';'.join(commands_1)
                    self.connect()
                    self.channel.execute(commands_1)
                    scripts = self.get_result(print_info=False).split('\n')
                    if '' in scripts:
                        scripts.remove('')
                if prog is None:
                    commands_1 = list(map(lambda x: 'chmod u+x ' + x, scripts))
                    commands_1 = ';'.join(commands_1)
                    commands_2 = ';'.join(scripts)
                    commands = commands_1 + ';' + commands_2
                else:
                    commands = list(
                        map(lambda x: '{} '.format(prog) + x, scripts))
                    commands = ';'.join(commands)
                _logger.info(commands)
                self.connect()
                print("=> Getting results:")
                self.channel.execute(commands)
            else:
                # Run local scripts
                #
                # 1) upload
                self.upload(scripts, dir, _logger)
                if data_dir is not None:
                    self.upload(data_dir, dir, _logger)
                # 2) get all file names
                if len(scripts) == 1:
                    if isdir(scripts[0]):
                        if list(scripts[0])[-1] == '/':
                            dir = os.path.join(
                                dir,
                                os.path.basename(os.path.dirname(scripts[0])))
                        else:
                            dir = os.path.join(dir,
                                               os.path.basename(scripts[0]))
                        scripts = glob.glob(scripts[0] + '/*')
                filelist = []
                for fp in scripts:
                    _logger.info("fp:%s" % fp)
                    fs = glob.glob(fp)
                    _logger.info("fs:%s" % fs)
                    for f in fs:
                        _logger.info("f:%s" % f)
                        if isdir(f):
                            print(
                                "Warning: directory %s is detected, note anything in it will be ignored to execute."
                                % f)
                        elif isfile(f):
                            filelist.append(f)
                        else:
                            print('Error: file %s does not exist.' % f)
                            sys.exit(1)
                filelist = list(map(os.path.basename, filelist))
                _logger.info(filelist)
                # 3) run them one by one
                scripts = list(map(lambda x: '/'.join([dir, x]), filelist))
                if prog is None:
                    commands_1 = list(map(lambda x: 'chmod u+x ' + x, scripts))
                    commands_1 = ';'.join(commands_1)
                    commands_2 = ';'.join(scripts)
                    commands = commands_1 + ';' + commands_2
                else:
                    commands = list(
                        map(lambda x: '{} '.format(prog) + x, scripts))
                    commands = ';'.join(commands)
                _logger.info(commands)
                self.connect()
                print("=> Getting results:")
                self.channel.execute(commands)

        datalist = self.get_result()
        # Return a string containing output
        return "".join(datalist)

    def get_result(self, print_info=True):
        """Get result from executed channel
        
        Args:
            print_info: if `True`, print information
        
        Returns:
            a string containing output from executed commands
        """
        size, errinfo = self.channel.read_stderr()
        if size > 0:
            print('An error is raised by remote host, please read the info:\n')
            print(errinfo.decode('utf-8', errors='replace'), end="")
            sys.exit(1)
        else:
            # Get output
            datalist = []
            size, data = self.channel.read()
            # Here data is byte type
            while size > 0:
                data = data.decode('utf-8', errors='ignore')
                if print_info:
                    print(data, sep='', end='')
                datalist.append(data)
                size, data = self.channel.read()

        # Return a string containing output from commands
        return "".join(datalist)

    def upload(self,
               source,
               destination,
               _logger,
               use_rsync=False,
               dry_run=False):
        """Upload files to active remote host.

        Currently, it is dependent on scp command.

        Args:
            source: list of files (directories) in local machine
            destination: destination directory in remote host
            _logger: the logging logger
            use_rsync: if `True`, use rsync instead of scp
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        username, host, port = self.active_host[1:]
        if dry_run:
            print("Running upload", ' '.join(source), "to", destination, "on",
                  tuple(self.active_host[1:]))
            sys.exit(0)
        # Make sure scp/rsync recognize destination as directory
        # Path must end with '/'
        if list(destination)[-1] != '/':
            destination = destination + '/'
        if use_rsync:
            if sys.platform == 'win32':
                print("--rsync is disabled in Windows, please don't use it.")
                sys.exit(0)
            cmds = "rsync -azP -e 'ssh -p {port}' {source} {username}@{host}:{destination}".format(
                port=port,
                source=' '.join(map(os.path.expanduser, source)),
                username=username,
                host=host,
                destination=destination)
        else:
            cmds = "scp -pr -P {port} {source} {username}@{host}:{destination}".format(
                port=port,
                source=' '.join(map(os.path.expanduser, source)),
                username=username,
                host=host,
                destination=destination)

        print("=> Starting upload...", end="\n\n")
        now = datetime.now()
        _logger.info("Running " + cmds)
        run_res = run(cmds, shell=True)
        _logger.info("Status code: " + str(run_res.returncode))
        if run_res.returncode != 0:
            print("Error: an error occurred, please check the info!")
            sys.exit(run_res.returncode)
        taken = datetime.now() - now
        print("\n=> Finished uploading in %ss" % taken.seconds)
        return

    def download(self,
                 source,
                 destination,
                 _logger,
                 use_rsync=False,
                 dry_run=False):
        """Download files to local machine from active remote host.
        
        Currently, it is dependent on scp command.

        Args:
            source: list of files (directories) in remote host
            destination: destination directory in local machine
            _logger: the logging logger
            use_rsync: if `True`, use rsync instead of scp
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        username, host, port = self.active_host[1:]
        if dry_run:
            print("Running download", ' '.join(source), "to", destination,
                  "from", tuple(self.active_host[1:]))
            sys.exit(0)
        if not isdir(os.path.expanduser(destination)):
            os.makedirs(os.path.expanduser(destination))
        # Make sure scp/rsync recognize destination as directory
        # Path must end with '/'
        if list(destination)[-1] != '/':
            destination = destination + '/'
        print("=> Starting downloading...", end="\n\n")
        now = datetime.now()
        if use_rsync:
            if sys.platform == 'win32':
                print("--rsync is disabled in Windows, please don't use it.")
                sys.exit(0)
            cmds = "rsync -azP -e 'ssh -p {port}' {username}@{host}:'{source}' {destination}".format(
                port=port,
                source=' '.join(source),
                username=username,
                host=host,
                destination=os.path.expanduser(destination))
        else:
            cmds = "scp -pr -P {port} {username}@{host}:'{source}' {destination}".format(
                port=port,
                source=' '.join(source),
                username=username,
                host=host,
                destination=os.path.expanduser(destination))
        _logger.info("Running " + cmds)
        run_res = run(cmds, shell=True)
        _logger.info("Status code: " + str(run_res.returncode))
        if run_res.returncode != 0:
            print("Error: an error occurred, please check the info!")
            sys.exit(run_res.returncode)
        taken = datetime.now() - now
        print("\n=> Finished downloading in %ss" % taken.seconds)
        return


class PBS:
    """
    Representation of PBS task
    """
    def __init__(self):
        self.tmp_header = os.path.join(data_dir, "PBS_HEADER.txt")
        self.tmp_cmds = os.path.join(data_dir, "PBS_CMDS.txt")
        self.pbs_template = os.path.join(data_dir, "pbs-template.pbs")
        self.samplefile = os.path.join(data_dir, "samplefile.csv")
        self.mapfile = os.path.join(data_dir, "mapping.csv")
        return

    def gen_template(self, input, output, dry_run=False):
        """Generate a PBS template
        
        Args:
            input: a string representing the path to template file
            output: a string representing the path to output file
            dyr_run: if `True`, dry run the code

        Returns:
            None
        """
        if output is None:
            output = os.path.join(os.getcwd(), 'work.pbs')
        print("=> Generating %s" % output)
        if dry_run:
            sys.exit(0)
        if isfile(output):
            print("Warning: the output file exists, it will be overwritten.")
        if input is None:
            with io.open(output, 'w', encoding='utf-8', newline='\n') as f:
                with open(self.tmp_header, 'r') as header:
                    for i in header:
                        print(i, file=f, sep='', end="")
            with io.open(output, 'a', encoding='utf-8', newline='\n') as f:
                with open(self.tmp_cmds, 'r') as cmds:
                    for i in cmds:
                        print(i, file=f, sep='', end="")
        else:
            if not isfile(input):
                print("Error: cannot find the template file.")
                sys.exit(1)
            with io.open(output, 'w', encoding='utf-8', newline='\n') as f:
                with open(input, 'r') as inf:
                    for i in inf:
                        print(i, file=f, sep='', end="")
        print("=> Done.")
        return

    def gen_pbs(self,
                template,
                samplefile,
                mapfile,
                outdir,
                _logger,
                pbs_mode=True,
                dry_run=False):
        """Generate a batch of (script) files (PBS tasks) based on template and mapping file
        
        Args:
            template: a string representing the path to the template file
            samplefile: a string representing the path to the sample file
            mapfile: a string representing the path to the mapping file
            outdir: a string representing the path to output directory
            _logger: the logging logger
            pbs_mode: if `True`, use PBS mode
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        if not isdir(outdir):
            print("Directory %s does not exist, creating it" % outdir)
            os.makedirs(outdir)
        if not isfile(template):
            print("Error: file %s does not exist" % template)
        if not isfile(samplefile):
            print("Error: file %s does not exist" % samplefile)
        if not isfile(mapfile):
            print("Error: file %s does not exist" % mapfile)

        print("=====================")
        print("Output path : " + outdir)
        if pbs_mode:
            print("PBS Template: " + template)
        else:
            print("Template: " + template)
        print("Sample file : " + samplefile)
        print("Mapping file: " + mapfile)
        print("=====================")

        if dry_run:
            sys.exit(0)

        print("=> Reading %s ..." % samplefile)
        sample_data = read_csv(samplefile)
        print("=> Reading %s ..." % mapfile)
        map_data = read_csv(mapfile)

        # Check if input files are valid
        check_list = [i[0] for i in sample_data]
        check_list = set(check_list)
        if len(sample_data) != len(check_list):
            print("Error: the first column is not unique!")
            sys.exit(1)
        for row in map_data:
            if len(row) != 2:
                print("Error: only two columns are quired in mapfile!")
            try:
                _ = int(row[1])
            except Exception:
                print(
                    "Error: the second column must be (or can be transformed to) an integer!"
                )
                sys.exit(1)

        print("=> Reading %s ..." % template)
        with open(template, 'r') as f:
            temp_data = f.read()

        print("Generating...")
        for row in sample_data:
            if pbs_mode:
                pbsfile = os.path.join(outdir, row[0] + '.pbs')
            else:
                pbsfile = os.path.join(outdir, row[0])
            _logger.info("Generating %s" % pbsfile)
            content = temp_data
            for i in map_data:
                try:
                    _logger.info("Replacing %s with %s" %
                                 (i[0], row[int(i[1])]))
                    content = content.replace(i[0], row[int(i[1])])
                except Exception:
                    print(
                        "Error: the second column out of range for label %s!" %
                        i[0])
            with io.open(pbsfile, 'w', encoding='utf-8', newline='\n') as f:
                f.write(content)
        print("Done.")
        return

    def gen_pbs_example(self, outdir, _logger, dry_run=False):
        """Generate example files for pbsgen command to specified directory
        
        Args:
            outdir: a string representing the output directory
            _logger: the logging logger
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        if not isdir(outdir):
            print("Directory %s does not exist, creating it" % outdir)
            os.makedirs(outdir)
        pbs_template = os.path.join(outdir,
                                    os.path.basename(self.pbs_template))
        samplefile = os.path.join(outdir, os.path.basename(self.samplefile))
        mapfile = os.path.join(outdir, os.path.basename(self.mapfile))
        print("=====================")
        print("Output path : " + outdir)
        print("PBS Template: " + pbs_template)
        print("Sample file : " + samplefile)
        print("Mapping file: " + mapfile)
        print("=====================")
        if dry_run:
            sys.exit(0)
        copyfile(self.pbs_template, pbs_template)
        copyfile(self.samplefile, samplefile)
        copyfile(self.mapfile, mapfile)
        print("Done.")
        return

    def sub(self, host, tasks, remote, workdir, _logger, dry_run=False):
        """Submit pbs tasks
        
        Args:
            host: a host object
            tasks: a list of PBS files, glob pattern is supported
            remote: if `True`, means that PBS task files are located at the active remote host
            workdir: a directory representing the working directory
            _logger: the logging logger
            dry_run: if `True`, dry run the code

        Returns:
            A list of files
        """
        print('NOTE: PBS file must be LF mode (Unix), not CRLF mode (Windows)')
        print('====================================================')
        filelist = []
        if remote:
            tasks = ' '.join(tasks)
            host.connect()
            _logger.info('ls -p ' + tasks)
            host.channel.execute('ls -p ' + tasks)
            filelist = host.get_result(print_info=False).split('\n')
            if '' in filelist:
                filelist.remove('')
            fl_bk = filelist.copy()
            for f in fl_bk:
                if len(f) > 1 and (f[-1] == '/' or f[-1] == ':'):
                    filelist.remove(f)
                if f == '' or f == ' ':
                    filelist.remove(f)
            _logger.info(filelist)
            if workdir is None:
                workdir = '/tmp'
            cmds = 'cd {}; for i in {}; do qsub $i; done'.format(
                workdir, ' '.join(filelist))

            if dry_run:
                print(cmds)
                sys.exit(0)
            _logger.info(cmds)
            host.cmd(cmds, _logger=_logger)
        else:
            if workdir is None:
                workdir = os.getcwd()
            for fp in tasks:
                fs = glob.glob(fp)
                for f in fs:
                    if isdir(f):
                        print(
                            "Warning: directory %s is detected, note anything in it will be ignored to execute."
                            % f)
                    elif isfile(f):
                        filelist.append(f)
                        cmds = 'cd ' + workdir + ';qsub ' + f

                        if dry_run:
                            print(cmds)
                        else:
                            _logger.info(cmds)
                            run(cmds, shell=True)
                    else:
                        print('Error: file %s does not exist.' % f)
                        sys.exit(1)
        return filelist

    def deploy(self,
               host,
               source,
               destination,
               _logger,
               use_rsync=False,
               dry_run=False):
        """Deploy target directory on the active remote host
        
        Upload the target destination and then submit all *.pbs files.

        Args:
            host: a host object
            source: a string representing the directory (contains .pbs files) to upload
            destination: a string representing the path on remote host
            _logger: the logging logger
            use_rsync: if `True`, use rsync instead of scp
            dry_run: if `True`, dry run the code

        Returns:
            None
        """
        if destination is None:
            destination = '/tmp'
        if dry_run:
            print("Running deploy", source, "to", destination, "on",
                  tuple(host.active_host[1:]))
            sys.exit(0)
        if not isdir(source):
            print("Error: directory %s does not exist" % source)
            sys.exit(1)
        source = [source]
        host.upload(source, destination, _logger, use_rsync=use_rsync)
        self.sub(host, [destination + '/*.pbs'], True, destination, _logger)
        return

    def check(self, host, job_id, dry_run=False):
        """Check PBS task status
        
        Args:
            host: a host object
            job_id: a string the job id
            dry_run: if `True`, dry run the code

        Returns:
            Job status
        """
        if job_id is None:
            if dry_run:
                print("Running qstat on", tuple(host.active_host[1:]))
                sys.exit(0)
            return host.cmd('qstat')
        else:
            if dry_run:
                print("Running qstat", job_id, "on",
                      tuple(host.active_host[1:]))
                sys.exit(0)
            return host.cmd('qstat ' + job_id)


if __name__ == "__main__":
    print(this_dir)
    print(data_dir)
