# Copyright 2012 Dusty Phillips

# This file is part of gitifyhg.

# gitifyhg is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# gitifyhg is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with gitifyhg.  If not, see <http://www.gnu.org/licenses/>.


from path import path as p
import pytest
import sh

from gitifyhg import clone, rebase


@pytest.fixture
def hg_repo(tmpdir):
    '''Fixture that creates an hg repository in a temporary directory
    gitifyhg can then be tested by cloaning that repo

    :param tmpdir: A temporary directory for the current test
    :return: a py.path inside the test's temporary directory that contains
        an initialized hg repository with a single commit'''
    tmpdir = p(tmpdir).abspath()
    hg_base = tmpdir.joinpath('hg_base')  # an hg repo to clone from
    hg_base.mkdir()
    sh.cd(hg_base)
    write_to_test_file('a\n')
    sh.hg.init()
    sh.hg.add('test_file')
    sh.hg.commit(message="a")
    sh.cd('..')

    return hg_base


@pytest.fixture
def git_dir(tmpdir):
    '''Fixture that creates a subdirectory in the tmpdir to hold the git clone.

    :param tmpdir: the temporary directory for the current test
    :return: a py.path inside the test's temporary directory that is an empty
        but existing directory.'''
    tmpdir = p(tmpdir).abspath()
    git_dir = tmpdir.joinpath('git_dir')
    git_dir.mkdir()
    return git_dir


# HELPERS
# =======
def write_to_test_file(message, filename='test_file'):
    '''Append the message to the 'test_file' file in the current working
    directory or filename if it was passed. This is normally done to stage a
    commit in hg or git.

    :param message: Something to be appended to the test file. Use \\n
        judiciously.
    :param filename: A filename to commit to. If unsupplied, test_file
        will be updated.'''
    with p(filename).open('a') as file:
        file.write(message)


def assert_git_count(count):
    '''Assuming you are in a git repository, assert that ``count`` commits
    have been made to that repo.'''
    assert sh.git.log(pretty='oneline').stdout.count(b'\n') == count


def assert_git_messages(expected_lines):
    '''Assert that logging all git messages in order provides the given lines
    of output.

    :param expected_lines: The a list of str messages  that were passed into
        git or hg when commited, in reverser order
        (ie: most recent commits at the top or left)
    :return True if the message lines match the git repo in the current directory
        False otherwise.'''
    actual_lines = sh.git('--no-pager', 'log', pretty='oneline', color='never'
        ).strip().split('\n')
    actual_lines = [l.partition(' ')[-1] for l in actual_lines]
    assert actual_lines == expected_lines


def assert_git_branch(branch_name):
    '''Assert that the git repo is on the named branch'''
    assert '* {}'.format(branch_name) in sh.git.branch().stdout.decode('UTF-8')


def assert_hg_count(count):
    '''Assuming you are in an hg repository, assert that ``count`` commits
    have been made to that repo.'''
    assert sh.grep(sh.hg.log(), 'changeset:').stdout.count(b'\n') == count


# THE ACTUAL TESTS
# ================
def test_clone(hg_repo, git_dir):
    '''Ensures that a clone of an upstream hg repository contains the
    appropriate structure.'''
    sh.cd(git_dir)
    clone(hg_repo)
    git_repo = git_dir.joinpath('hg_base')
    hg_clone = git_repo.joinpath('.gitifyhg/hg_clone')

    assert git_repo.exists()
    assert git_repo.joinpath('test_file').exists()
    assert git_repo.joinpath('.git').isdir()
    assert hg_clone.joinpath('test_file').exists()
    assert hg_clone.joinpath('.hg').isdir()
    assert git_repo.joinpath('.gitifyhg/patches/').isdir()
    assert len(git_repo.joinpath('.gitifyhg/patches/').listdir()) == 0

    sh.cd(git_repo)
    assert_git_count(1)
    assert len(sh.git.status(short=True).stdout) == 0

    sh.cd(hg_clone)
    assert_hg_count(1)
    assert len(sh.hg.status().stdout) == 0


def test_no_clone_branches(hg_repo, git_dir):
    '''When cloning an upstream hg repository that has branches, only clone
    the default branch. This is probably not going to be desired behavior
    forever and ever, but it works for now.'''

    sh.cd(hg_repo)
    sh.hg.branch('ignore_me')
    write_to_test_file('b\n')
    sh.hg.commit(message="b")
    write_to_test_file('c\n')
    sh.hg.commit(message="c")

    sh.cd(git_dir)
    clone(hg_repo)
    git_repo = git_dir.joinpath('hg_base')
    assert git_repo.exists()
    with open(git_repo.joinpath('test_file')) as file:
        assert file.read() == 'a\n'
    assert_git_count(1)


def test_clone_merged_branch(hg_repo, git_dir):
    '''When cloning branches in upstream commits, ignore commits that happened
    on other branches, and use only the merge commits.'''
    sh.cd(hg_repo)
    sh.hg.branch('merge_me')
    write_to_test_file('b\n')
    sh.hg.commit(message="b")
    write_to_test_file('c\n')
    sh.hg.commit(message="c")
    sh.hg.update('default')
    sh.hg.merge('merge_me')
    sh.hg.commit(message="merge")

    sh.cd(git_dir)
    clone(hg_repo)
    git_repo = git_dir.joinpath('hg_base')
    assert git_repo.exists()
    with open(git_repo.joinpath('test_file')) as file:
        assert file.read() == 'a\nb\nc\n'
    assert_git_count(2)
    # If you are a git user, you're probably wtfing now. The original commit
    # and the merge commit are on the default branch. The other commits do
    # not get included cause they only exist on the other branch. All their
    # changes got blobbed into a single merge commit that is hard to read
    # THIS IS WHY I WROTE GITIFYHG IN THE FIRST PLACE.


def test_clean_rebase(hg_repo, git_dir):
    '''When changes have happened upstream but not in the local git repo,
    ensure that a call to rebase updates everything.'''
    sh.cd(git_dir)
    git_repo = git_dir.joinpath('hg_base')
    hg_clone = git_repo.joinpath('.gitifyhg/hg_clone')
    clone(hg_repo)

    sh.cd(hg_repo)
    write_to_test_file('b\n')
    sh.hg.commit(message="b")
    write_to_test_file('c\n')
    sh.hg.commit(message="c")

    sh.cd(git_repo)
    rebase()

    assert_git_count(3)
    assert_git_messages(['c', 'b', 'a'])
    assert_git_branch('master')
    assert len(git_repo.joinpath('.gitifyhg/patches/').listdir()) == 0

    sh.cd(hg_clone)
    assert_hg_count(3)


def test_rebase_with_changes(hg_repo, git_dir):
    '''When changes have happened both upstream and on local master, ensure
    that a call to rebase does the right thing.'''

    sh.cd(git_dir)
    git_repo = git_dir.joinpath('hg_base')
    hg_clone = git_repo.joinpath('.gitifyhg/hg_clone')
    clone(hg_repo)

    sh.cd(git_repo)
    write_to_test_file('d', 'd')
    sh.git.add('d')
    sh.git.commit(message='d')
    write_to_test_file('e', 'e')
    sh.git.add('e')
    sh.git.commit(message='e')

    sh.cd(hg_repo)
    write_to_test_file('b\n')
    sh.hg.commit(message="b")
    write_to_test_file('c\n')
    sh.hg.commit(message="c")

    sh.cd(git_repo)
    rebase()

    assert_git_count(5)
    assert_git_branch('master')
    assert_git_messages(['e', 'd', 'c', 'b', 'a'])

    sh.cd(hg_clone)
    assert_hg_count(3)
