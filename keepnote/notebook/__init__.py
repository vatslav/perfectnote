"""

    KeepNote    
    Notebook data structure

"""

#
#  KeepNote
#  Copyright (c) 2008-2009 Matt Rasmussen
#  Author: Matt Rasmussen <rasmus@mit.edu>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301, USA.
#


# python imports
import gettext
import mimetypes
import os
import sys
import shutil
import re
import traceback
import urlparse
import urllib2
import uuid

# xml imports
from xml.sax.saxutils import escape
import xml.etree.cElementTree as ET


# keepnote imports
from keepnote.listening import Listeners
from keepnote.timestamp import get_timestamp
from keepnote import safefile
from keepnote import trans
from keepnote.notebook import index as notebook_index
from keepnote import orderdict
from keepnote import plist
from keepnote.pref import Pref
import keepnote


_ = trans.translate



# NOTE: the <?xml ?> header is left off to keep it compatiable with IE,
# for the time being.
# constants
BLANK_NOTE = u"""\
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><body></body></html>
"""

XML_HEADER = u"""\
<?xml version="1.0" encoding="UTF-8"?>
"""

NOTEBOOK_FORMAT_VERSION = 4
ELEMENT_NODE = 1
NODE_META_FILE = u"node.xml"
PAGE_DATA_FILE = u"page.html"
PLAIN_TEXT_DATA_FILE = u"page.txt"
PREF_FILE = u"notebook.nbk"
NOTEBOOK_META_DIR = u"__NOTEBOOK__"
NOTEBOOK_ICON_DIR = u"icons"
TRASH_DIR = u"__TRASH__"
TRASH_NAME = u"Trash"
DEFAULT_PAGE_NAME = u"New Page"
DEFAULT_DIR_NAME = u"New Folder"

# content types
CONTENT_TYPE_PAGE = u"text/xhtml+xml"
#CONTENT_TYPE_PLAIN_TEXT = "text/plain"
CONTENT_TYPE_TRASH = u"application/x-notebook-trash"
CONTENT_TYPE_DIR = u"application/x-notebook-dir"
CONTENT_TYPE_UNKNOWN = u"application/x-notebook-unknown"

NULL = object()

# the node id of the implied root of all nodes everywhere
UNIVERSAL_ROOT = u"b810760f-f246-4e42-aebb-50ce51c3d1ed"


#=============================================================================
# filename creation functions

REGEX_SLASHES = re.compile(ur"[/\\]")
REGEX_BAD_CHARS = re.compile(ur"[\?'&<>|`:;]")
REGEX_LEADING_UNDERSCORE = re.compile(ur"^__+")

def get_valid_filename(filename, default=u"folder"):
    """Converts a filename into a valid one
    
    Strips bad characters from filename
    """
    
    filename = re.sub(REGEX_SLASHES, u"-", filename)
    filename = re.sub(REGEX_BAD_CHARS, u"", filename)
    filename = filename.replace(u"\t", " ")
    filename = filename.strip(u" \t.")
    
    # don't allow files to start with two underscores
    filename = re.sub(REGEX_LEADING_UNDERSCORE, u"", filename)
    
    # don't allow pure whitespace filenames
    if filename == u"":
        filename = default
    
    # use only lower case, some filesystems have trouble with mixed case
    filename = filename.lower()
    
    return filename
    

def get_unique_filename(path, filename, ext=u"", sep=u" ", number=2,
                        return_number=False, use_number=False):
    """Returns a unique version of a filename for a given directory"""

    if path != u"":
        assert os.path.exists(path), path
    
    # try the given filename
    if not use_number:
        newname = os.path.join(path, filename + ext)
        if not os.path.exists(newname):
            if return_number:
                return (newname, None)
            else:
                return newname
    
    # try numbered suffixes
    i = number
    while True:
        newname = os.path.join(path, filename + sep + unicode(i) + ext)
        if not os.path.exists(newname):
            if return_number:
                return (newname, i)
            else:
                return newname
        i += 1


def get_valid_unique_filename(path, filename, ext=u"", sep=u" ", number=2):
    """Returns a valid and unique version of a filename for a given path"""
    return get_unique_filename(path, get_valid_filename(filename), 
                               ext, sep, number)
    

def get_unique_filename_list(filenames, filename, ext=u"", sep=u" ", number=2):
    """Returns a unique filename for a given list of existing files"""
    filenames = set(filenames)
    
    # try the given filename
    newname = filename + ext
    if newname not in filenames:
        return newname
    
    # try numbered suffixes
    i = number
    while True:
        newname = filename + sep + unicode(i) + ext
        if newname not in filenames:
            return newname
        i += 1


def relpath(filename, start):
    """
    Returns the relative filename to start

    This is implemented to provide python2.5 support.
    """

    filename = os.path.normpath(filename)
    start = os.path.normpath(start)

    if filename.startswith(start):
        filename = filename[len(start):]
        while filename.startswith(os.path.sep):
            filename = filename[1:]
        return filename
    else:
        raise Excpetion("unhandled case")
        
    

#=============================================================================
# File naming scheme


def get_node_meta_file(nodepath):
    """Returns the metadata file for a node"""
    return os.path.join(nodepath, NODE_META_FILE)

def get_page_data_file(pagepath):
    """Returns the HTML data file for a page"""
    return os.path.join(pagepath, PAGE_DATA_FILE)

def get_plain_text_data_file(pagepath):
    """Returns the plain text data file for a page"""
    return os.path.join(pagepath, PLAIN_TEXT_DATA_FILE)

def get_pref_file(nodepath):
    """Returns the filename of the notebook preference file"""
    return os.path.join(nodepath, PREF_FILE)

def get_pref_dir(nodepath):
    """Returns the directory of the notebook preference file"""
    return os.path.join(nodepath, NOTEBOOK_META_DIR)

def get_icon_dir(nodepath):
    """Returns the directory of the notebook icons"""
    return os.path.join(nodepath, NOTEBOOK_META_DIR, NOTEBOOK_ICON_DIR)

def get_trash_dir(nodepath):
    """Returns the trash directory of the notebook"""
    return os.path.join(nodepath, TRASH_DIR)


def normalize_notebook_dirname(filename, longpath=None):
    """
    Normalize a notebook filename

    If the filename contains 'path/to/the-notebook/notebook.nbk', then 
    return 'path/to/the-notebook'.

    If the platform is windows (or longpath=True), then return the long 
    file name prefix '\\\\?\\'.
    """

    filename = keepnote.ensure_unicode(filename, keepnote.FS_ENCODING)

    # allow long file paths in windows
    if (longpath is True or 
        (longpath is None and keepnote.get_platform() == "windows")):
        filename = "\\\\?\\" + filename

    # ensure filename points to notebook directory
    if os.path.isdir(filename):
        return filename
    elif os.path.isfile(filename):
        # filename may be 'path/to/the-notebook/notebook.nbk'
        return os.path.dirname(filename)
    else:
        raise NoteBookError(_("Cannot find notebook '%s'" % filename))


#=============================================================================
# HTML functions

TAG_PATTERN = re.compile(u"<[^>]*>")
def strip_tags(line):
    return re.sub(TAG_PATTERN, u"", line)

def read_data_as_plain_text(infile):
    """Read a Note data file as plain text"""

    # TODO: need to handle case when <body> and </body> are on same line

    for line in infile:
        # skip until body tag
        if "<body>" in line:
            pos = line.find("<body>")
            if pos != -1:
                yield strip_tags(line[pos+6:])
                break

    # yield until </body>
    for line in infile:
        pos = line.find("</body>")
        if pos != -1:
            yield strip_tags(line[:pos])
            break

        # strip tags
        yield strip_tags(line)



#=============================================================================
# functions

def get_notebook_version(filename):
    """Read the version of a notebook from its preference file"""
    
    if os.path.isdir(filename):
        filename = get_pref_file(filename)

    try:
        tree = ET.ElementTree(file=filename)
    except IOError, e:
        raise NoteBookError(_("Cannot read notebook preferences"), e)
    except Exception, e:
        raise NoteBookError(_("Notebook preference data is corrupt"), e)

    return get_notebook_version_etree(tree)


def get_notebook_version_etree(tree):
    """Read the version of a notebook from an ElementTree"""
    
    root = tree.getroot()
    if root.tag == "notebook":
        p = root.find("version")
        if p is None:
            # assume latest version
            return NOTEBOOK_FORMAT_VERSION

        if not p.text.isdigit():
            raise NoteBookError(_("Unknown version string"))

        return int(p.text)
    else:
        raise NoteBookError(_("Notebook preference data is corrupt"), e)



def new_nodeid():
    """Generate a new node id"""
    return unicode(uuid.uuid4())


def get_node_url(nodeid, host=u""):
    """Get URL for a nodeid"""
    return u"nbk://%s/%s" % (host, nodeid)


def is_node_url(url):
    return re.match(u"nbk://[^/]*/.*", url) != None

def parse_node_url(url):
    match = re.match(u"nbk://([^/]*)/(.*)", url)
    if match:
        return match.groups()
    else:
        raise Exception("bad node URL")
    

def guess_file_mimetype(filename, default="application/octet-stream"):
    """Guess the mimetype of a file by its filename"""
    content_type = mimetypes.guess_type(filename)[0]
    if content_type is None:
        return default
    else:
        return content_type


def attach_file(filename, node, index=None):
    """Attach a file to a node in a notebook"""

    # cannot attach directories (yet)
    if os.path.isdir(filename):
        return None

    # determine content-type
    content_type = guess_file_mimetype(filename)
    new_filename = os.path.basename(filename)

    try:
        child = node.new_child(content_type, new_filename, index)
        child.set_payload(filename, new_filename)
        child.save(True)
        return child

    except Exception, e:
        # remove child
        keepnote.log_error(e)
        if child:
            child.delete()
        raise e



#=============================================================================
# errors

class NoteBookError (StandardError):
    """Exception that occurs when manipulating NoteBook's"""
    
    def __init__(self, msg, error=None):
        StandardError.__init__(self)
        self.msg = msg
        self.error = error
    
    
    def __str__(self):
        if self.error is not None:
            return repr(self.error) + "\n" + self.msg
        else:
            return self.msg


class NoteBookVersionError (NoteBookError):
    """Exception for version errors while reading notebooks"""

    def __init__(self, notebook_version, readable_version,  error=None):
        NoteBookError.__init__(self,
            "Notebook version '%d' is higher than what is readable '%d'" %
                               (notebook_version,
                                readable_version),
                               error)
        self.notebook_version = notebook_version
        self.readable_version = readable_version


#=============================================================================
# notebook attributes

# TODO: finish

class AttrDef (object):
    """
    A AttrDef is a metadata attribute that can be associated to
    nodes in a NoteBook.
    """

    def __init__(self, name, datatype, key=None, write=None, read=None,
                 default=None):
        if key == None:
            self.key = name
        else:
            self.key = key
        self.name = name
        self.datatype = datatype

        
        # writer function
        if write is None:
            if datatype == bool:
                self.write = lambda x: unicode(int(x))
            else:
                self.write = unicode
        else:
            self.write = write

        # reader function
        if read is None:
            if datatype == bool:
                self.read = lambda x: bool(int(x))
            else:
                self.read = datatype
        else:
            self.read = read

        # default function
        if default is None:
            self.default = datatype
        else:
            self.default = default
        

class UnknownAttr (object):
    """A value that belongs to an unknown AttrDef"""

    def __init__(self, value):
        self.value = value

        

class NoteBookTable (object):
    def __init__(self, name, attrs=[]):
        self.name = name
        self.attrs = list(attrs)

        # TODO: add col widths
        # NoteBooks have tables and attrs



# mapping for old style of saving sort order
_sort_info_backcompat = {"0": "order",
                         "1": "order",
                         "2": "title",
                         "3": "created_time",
                         "4": "modified_time"} 
def read_info_sort(key):
    return _sort_info_backcompat.get(key, key)


title_attr = AttrDef("Title", unicode, "title")
created_time_attr = AttrDef("Created", int, "created_time", default=get_timestamp)
modified_time_attr = AttrDef("Modified", int, "modified_time", default=get_timestamp)

g_default_attr_defs = [
    title_attr,
    AttrDef("Content type", unicode, "content_type",
                 default=lambda: CONTENT_TYPE_DIR),
    AttrDef("Order", int, "order", default=lambda: sys.maxint),
    created_time_attr,
    modified_time_attr,
    AttrDef("Expaned", bool, "expanded", default=lambda: True),
    AttrDef("Expanded2", bool, "expanded2", default=lambda: True),
    AttrDef("Folder Sort", unicode, "info_sort", read=read_info_sort,
                 default=lambda: "order"),
    AttrDef("Folder Sort Direction", int, "info_sort_dir", 
                 default=lambda: 1),
    AttrDef("Node ID", unicode, "nodeid", default=new_nodeid),
    AttrDef("Icon", unicode, "icon"),
    AttrDef("Icon Open", unicode, "icon_open"),
    AttrDef("Filename", unicode, "payload_filename"),
    AttrDef("Duplicate of", unicode, "duplicate_of")
]


default_notebook_table = NoteBookTable("default", attrs=[title_attr,
                                                         created_time_attr,
                                                         modified_time_attr])



# TODO: parent might be an implict attr


# 1. attrs should be data that is optional (although keepnote has a few
# required entries).
# 2. attrs can appear in listview




#=============================================================================
# Notebook nodes

class NoteBookNode (object):
    """A general base class for all nodes in a NoteBook"""

    def __init__(self, title=u"", parent=None, notebook=None,
                 content_type=CONTENT_TYPE_DIR, conn=None):
        self._notebook = notebook
        self._conn = conn if conn else self._notebook._conn
        self._parent = parent
        self._basename = None
        self._children = None
        self._has_children = None
        self._valid = True
        self._version = NOTEBOOK_FORMAT_VERSION
        
        self.clear_attr(title=title, content_type=content_type)

        # TODO: add a mechanism to register implict attrs that in turn do lookup
        # "parent", "nchildren"
        
        
    def is_valid(self):
        """Returns True if node is valid (not deleted)"""
        return self._valid
    
    def get_version(self):
        """Returns the format version of this node"""
        return self._version
    
    def get_notebook(self):
        """Returns the notebook that owns this node"""
        return self._notebook


    #==============================================
    # filesystem path functions

    def get_path(self):
        """Returns the directory path of the node"""
        return self._conn.get_node_path(self)

    def get_name_path(self):
        """Returns list of basenames from root to node"""
        return self._conn.get_node_name_path(self)    
    
    def _set_basename(self, path):
        """Sets the basename directory of the node"""
        self._conn.set_node_basename(self, path)
        

    def get_basename(self):
        """Returns the basename of the node"""
        return self._basename

    def get_url(self, host=""):
        """Returns URL for node"""
        return get_node_url(self._attr["nodeid"], host)


    #=======================================
    # attr functions
    
    def clear_attr(self, title="", content_type=CONTENT_TYPE_DIR):
        """Clear attributes (set them to defaults)"""

        # TODO: generalize this
        # make clear method in attributes
        self._attr = {
            "title": title,
            "content_type": content_type,
            "order": sys.maxint,
            "created_time": None,
            "modified_time": None,
            "expanded": True,
            "expanded2": True,
            "info_sort": "order",
            "info_sort_dir": 1}
        
    
    def get_attr(self, name, default=None):
        """Get the value of an attribute"""
        return self._attr.get(name, default)

    def set_attr(self, name, value):
        """Set the value of an attribute"""
        oldvalue = self._attr.get(name, NULL)
        self._attr[name] = value

        # if attr is one that the notebook manages then we are dirty
        # TODO: should have additional test that attr needs to be saved
        # this test is added for the icon_loaded attr, which is not needed to
        # to be saved
        if name in self._notebook.attr_defs and value != oldvalue:
            self._set_dirty(True)

    def has_attr(self, name):
        """Returns True if node has the attribute"""
        return name in self._attr


    def del_attr(self, name):
        """Delete an attribute from the node"""

        # TODO: check against un-deletable attributes
        if name in self._attr:
            del self._attr[name]

        if name in self._notebook.attr_defs:
            self._set_dirty(True)
        

    def iter_attr(self):
        """Iterate through attributes of the node"""
        return self._attr.iteritems()
    

    def set_attr_timestamp(self, name, timestamp=None):
        """Set a timestamp attribute"""
        if timestamp is None:
            timestamp = get_timestamp()
        self._attr[name] = timestamp
        self._set_dirty(True)
        

    def get_title(self):
        """Returns the display title of a node"""
        return self._attr.get("title", "")
    
    
    def get_parent(self):
        """Returns the parent of the node"""
        return self._parent

    

    #=============================================
    # filesystem methods

    def create(self):
        """Initializes the node on disk (create required files/directories)"""

        self._attr["created_time"] = get_timestamp()
        self._attr["modified_time"] = get_timestamp()
        self._conn.create_node(self)
        self._set_dirty(False)
       
    
    def delete(self):
        """Deletes this node from the notebook"""

        # perform delete on disk
        self._conn.delete_node(self)
        
        # update data structure
        self._parent._remove_child(self)
        self._parent._set_child_order()
        self._valid = False
        self._set_dirty(False)
        
        # make sure to recursively invalidate
        def walk(node):
            """Uncache children list"""

            self._notebook._index.remove_node(self)

            if node._children is not None:
                for child in node._children:
                    child._valid = False
                    walk(child)
        walk(self)

        # parent node notifies listeners of change
        self._parent.notify_change(True)
    
    
    def trash(self):
        """Places node in the notebook's trash folder"""

        if self._notebook is None:
            raise NoteBookError(_("This node is not part of any notebook"))
        
        if self.in_trash():
            # delete if in trash folder already
            self.delete()
        else:
            # move to trash            
            self.move(self._notebook._trash)
        
        
    
    def in_trash(self):
        """Determines if node is inside Trash folder"""
        
        # TODO: become more complicated with general graph structure
        # trace up through parents
        ptr = self._parent
        while ptr is not None:
            if ptr == self._notebook._trash:
                return True
            ptr = ptr._parent
        return False
    
    
    def move(self, parent, index=None):
        """Move this node to be the child of another node 'parent'"""
        
        # TODO: if parent is in another notebook, index updates need to be
        # done for whole subtree.  Also accessory data like icons might need
        # to be transferred.
        
        assert self != parent
        old_parent = self._parent
        
        # make sure new parents children are loaded
        parent.get_children()

        # perform on-disk move if new parent
        if old_parent != parent:
            new_path = self._conn.move_node(self, parent)
            self._set_basename(new_path)
            self._notebook._index.add_node(self)
            

        # perform move in data structure
        self._parent._remove_child(self)
        if self._parent != parent:
            self._parent._set_child_order()
            self._parent = parent
            self._parent._add_child(self, index)
        else:
            if self._attr["order"] < index:
                index -= 1
            self._parent._add_child(self, index)
        self._set_dirty(True)
        self.save(True)

        # notify listeners
        if parent != old_parent:
            self.notify_changes([old_parent, parent], True)
        else:
            old_parent.notify_change(True)


    def rename(self, title):
        """Renames the title of the node"""
        
        # do nothing if title is the same
        if title == self._attr["title"]:
            return
        
        if self._parent is None:
            # don't rename the directory of the notebook itself
            # just change the title
            self._attr["title"] = title
            self._set_dirty(True)
        else:

            try:
                path2 = self._conn.rename_node(self, title)
                self._attr["title"] = title
                self._set_basename(path2)
                self.save(True)
            except NoteBookError, e:
                raise NoteBookError(_("Cannot rename '%s' to '%s'" % (path, path2)), e)
        
        self._notebook._index.add_node(self)
        self.notify_change(False)


    def new_child(self, content_type, title, index=None):
        """Add a new node under this node"""
        
        self.get_children()
        node = self._notebook.new_node(content_type, None, self, 
                                       {"title": title})
        node.create()
        self._add_child(node, index)
        node.save(True)
        self.notify_change(True)
        return node
    

    def _new_child(self, content_type, title, index=None):
        """Add a new node under this node
           Private method.  Does not notify listeners.
        """
        
        self.get_children()
        node = self._notebook.new_node(content_type, None, self, 
                                       {"title": title})
        node.create()
        self._add_child(node, index)
        node.save(True)
        return node
    

    
    def duplicate(self, parent, index=None, recurse=False, notify=True,
                  skip=None):
        """Duplicate a node to a new parent"""

        # NOTE: we must be able to handle the case where the root node is
        # duplicated.
        
        # initialize skip set to prevent double copying
        if skip is None:
            skip = set()
        if self in skip:
            # skip this node if it has just been copied
            return None

        # create new node
        node = parent._new_child(self.get_attr("content_type"),
                                 self.get_attr("title"),
                                 index=index)
        skip.add(node)

        # copy attributes
        for key, value in self.iter_attr():
            if key not in ("nodeid", "order"):
                node._attr[key] = value

        # record the nodeid of the original node
        node._attr["duplicate_of"] = self.get_attr("nodeid")

        node.write_meta_data()

        # copy files
        try:
            self._conn.copy_node_files(self, node)
        except Exception, e:
            print e
            # TODO: handle errors
            pass

        # update index
        self._notebook._index.add_node(node)

        # TODO: prevent loops, copy paste within same tree.
        if recurse:
            for child in self.get_children():
                child.duplicate(node, recurse=True, notify=False,
                                skip=skip)

        if notify:
            parent.notify_change(True)

        return node



    #==================================
    # child management

    def get_children(self):
        """Returns all children of this node"""
        if self._children is None:
            self._get_children()
        return self._children


    def has_children(self):
        """Return True if node has children"""
        if self._children is None:
            if self._has_children is None:
                try:
                    self.iter_temp_children().next()
                    self._has_children = True
                except StopIteration:
                    self._has_children = False
            return self._has_children
        else:
            return len(self._children) > 0
    
    
    def _get_children(self):
        """Load children list from filesystem"""
        self._children = []

        for node in self.iter_temp_children():
            self._children.append(node)                    
            # notify index
            self._notebook._index.add_node(node)

        # assign orders
        self._children.sort(key=lambda x: x._attr["order"])
        self._set_child_order()


    def iter_temp_children(self):
        """Iterate through children
           Returns temporary node objects
        """
        for path in self._conn.node_list_children(self):
            try:
                yield self._notebook.read_node(self, path)
            except NoteBookError, e:
                print >>sys.stderr, "error reading", path2
                traceback.print_exception(*sys.exc_info())
                continue
                # TODO: raise warning, not all children read
    
    
    def _set_child_order(self):
        """Ensures that child know their order in the children list"""
        for i, child in enumerate(self._children):
            if child._attr["order"] != i:
                child._attr["order"] = i
                child._set_dirty(True)


    def add_child(self, child, index=None):
        """Add node as a child"""
        self._add_child(child, index)
        self.notify_change(True)
        

    def _add_child(self, child, index=None):
        """Add a node as a child"""
        
        # propogate notebook
        child._notebook = self._notebook
        
        # determine insert location
        if self._children is None:
            self._get_children()
        
        if index is not None:
            # insert child at index
            self._children.insert(index, child)
            self._set_child_order()
        elif (self._notebook and len(self._children) > 0 and 
              self._children[-1] == self._notebook.get_trash()):
            # append child before trash
            self._children.insert(len(self._children)-1, child)
            self._set_child_order()
        else:
            # append child at end of list
            child._attr["order"] = len(self._children)
            self._children.append(child)

        # notify index and mark dirty
        self._notebook._index.add_node(child)
        child._set_dirty(True)
    

    def _remove_child(self, child):
        """Remove a child node"""
        if self._children is None:
            self._get_children()
        self._children.remove(child)


    def allows_children(self):
        """Returns True is this node allows children"""
        return True
    

    #==============================================
    # low-level input/output
    
    def load(self):
        """Load a node from filesystem"""
        self.read_meta_data()
        
    def save(self, force=False):
        """Save node if modified (dirty)"""
        if (force or self._is_dirty()) and self._valid:
            self.write_meta_data()
            self._set_dirty(False)
            

    def get_data_file(self):
        """Returns filename of data/text/html/etc"""
        return self._conn.get_node_file(self, PAGE_DATA_FILE)

    def get_file(self, filename):
        return self._conn.get_node_file(self, filename)

    def open_file(self, filename, mode="r", codec="utf-8"):
        return self._conn.open_node_file(
            self, filename, mode, codec=codec)

    def new_filename(self, new_filename, ext=u"", sep=u" ", number=2, 
                     return_number=False, use_number=False, ensure_valid=True):
        return self._conn.new_filename(
            self, new_filename, ext, sep, number, 
            return_number=return_number, use_number=use_number, 
            ensure_valid=ensure_valid)

        
    def get_meta_file(self):
        """Returns the meta file for the node"""
        return get_node_meta_file(self.get_path())

    def write_meta_data(self):
        self._notebook.write_node_meta_data(self)

    def read_meta_data(self):
        self._notebook.read_node_meta_data(self)

    def set_meta_data(self, attr):
        self._version = attr.get("version", NOTEBOOK_FORMAT_VERSION)
        
        # set defaults
        for key in self._notebook.get_necessary_attrs():
            if key not in attr:
                attr[key] = self._notebook.attr_defs[key].default()
                self._set_dirty(True)
        
        self._attr.update(attr)


    #=============================================
    # marking for save needed

    def _set_dirty(self, dirty):
        """Sets the dirty bit to indicates whether node needs saving"""
        self._notebook._set_dirty_node(self, dirty)
        
    def _is_dirty(self):
        """Returns True if node needs saving"""
        return self._notebook._is_dirty_node(self)
        
    def mark_modified(self):
        """Marks a node as modified or dirty"""
        self._notebook._set_dirty_node(self, True)

    #===============================================
    # listeners
    
    def notify_change(self, recurse):
        """Notify listeners that node has changed"""
        if self._notebook:
            self._notebook.node_changed.notify([self], recurse)

    def notify_changes(self, nodes, recurse):
        """Notify listeners that several nodes have changed"""
        if self._notebook:
            self._notebook.node_changed.notify(nodes, recurse)
    
    def suppress_change(self, listener=None):
        """Suppress notification of listeners for node changes"""
        if self._notebook:
            self._notebook.node_changed.suppress(listener)

    def resume_change(self, listener=None):
        """Resume notification of listeners for node changes"""        
        if self._notebook:
            self._notebook.node_changed.resume(listener)


#=============================================================================
# NoteBookNode subclasses


class NoteBookPage (NoteBookNode):
    """Class that represents a Page in the NoteBook"""
    
    def __init__(self, title=DEFAULT_PAGE_NAME,
                 parent=None, notebook=None):
        NoteBookNode.__init__(self, title, parent, notebook,
                              content_type=CONTENT_TYPE_PAGE)


    def create(self):
        NoteBookNode.create(self)
        self.write_empty_data_file()


    def read_data_as_plain_text(self):
        """Iterates over the lines of the data file as plain text"""
        infile = self._conn.open_node_file(
            self, PAGE_DATA_FILE, "r", codec="utf-8")
        for line in read_data_as_plain_text(infile):
            yield line

        infile.close()
            
    
    def write_empty_data_file(self):
        """Initializes an empty data file on file-system"""
        try:
            out = self._conn.open_node_file(
                self, PAGE_DATA_FILE, "w", codec="utf-8")
            out.write(BLANK_NOTE)
            out.close()
        except IOError, e:
            raise NoteBookError(
                _("Cannot initialize richtext file '%s'" % datafile), e)
        


class NoteBookDir (NoteBookNode):
    """Class that represents Folders in NoteBook"""
    
    def __init__(self, title=DEFAULT_DIR_NAME,
                 parent=None, notebook=None):
        NoteBookNode.__init__(self, title, parent, notebook,
                              content_type=CONTENT_TYPE_DIR)


class NoteBookGenericFile (NoteBookNode):
    """Class that generic file in NoteBook"""
    
    def __init__(self, filename=None, title=None, content_type=None,
                 parent=None, notebook=None):

        if filename:
            if title is None:
                title = os.path.basename(filename)

            if content_type is None:
                content_type = mimetypes.guess_type(filename)[0]

        else:
            title = _("New File")

            if content_type is None:
                content_type = "application/octet-stream"
        
        NoteBookNode.__init__(self, title, parent, notebook,
                              content_type=content_type)

        if filename:
            self._attr["payload_filename"] = filename
        


    def set_payload(self, filename, new_filename=None):
        """Copy file into NoteBook directory"""

        # determine new file name
        if new_filename is None:
            new_filename = os.path.basename(filename)
        
        new_filename = self._conn.new_filename(self, new_filename, None)
        
        try:
            # attempt url parse
            parts = urlparse.urlparse(filename)
            
            if os.path.exists(filename) or parts[0] == "":
                # perform local copy
                self._conn.copy_node_file(None, filename, self, new_filename)
            else:
                # perform download
                out = self.open_file(new_filename, "wb")
                infile = urllib2.urlopen(filename)
                while True:
                    data = infile.read(1024*4)
                    if data == "":
                        break
                    out.write(data)
                infile.close()
                out.close()
        except IOError, e:
            raise NoteBookError(_("Cannot copy file '%s'" % filename), e)
        
        # set attr
        self._attr["payload_filename"] = new_filename


class NoteBookTrash (NoteBookDir):
    """Class represents the Trash Folder in a NoteBook"""

    def __init__(self, name, notebook):
        NoteBookDir.__init__(self,  
                             name, parent=notebook, notebook=notebook)
        self.set_attr("content_type", CONTENT_TYPE_TRASH)
        
        
    def move(self, parent, index=None):
        """Trash folder only be under root directory"""
        
        if parent == self._notebook:
            assert parent == self._parent
            NoteBookDir.move(self, parent, index)
        else:
            raise NoteBookError(
                _("The Trash folder must be a top-level folder."))
    
    def delete(self):
        """Trash folder cannot be deleted"""
        
        raise NoteBookError(_("The Trash folder cannot be deleted."))



#=============================================================================
# Notebook preferences


class NoteBookPreferences (Pref):
    """Preference data structure for a NoteBook"""
    def __init__(self):
        keepnote.Pref.__init__(self)
        
        self.quick_pick_icons_changed = Listeners()
        self.init()


    def set_data(self, data):
        self.init()
        self._data = data


    def get_data(self):
        return self._data


    def init(self):
        self._data["version"] = NOTEBOOK_FORMAT_VERSION
        self._data["quick_pick_icons"] = []

        self.quick_pick_icons_changed.notify()


    def get_quick_pick_icons(self):
        return self._data["quick_pick_icons"]

    def set_quick_pick_icons(self, icons):
        self._data["quick_pick_icons"] = list(icons)
        self.quick_pick_icons_changed.notify()
        

    
#=============================================================================
# NoteBook type


class NoteBook (NoteBookDir):
    """Class represents a NoteBook"""

    # TODO: should I make a base class with a filename argument?
    # TODO: replace os.path.basename with conn
    
    def __init__(self, rootdir=None):
        """rootdir -- Root directory of notebook"""

        self._conn = None
        NoteBookDir.__init__(self, notebook=self)
        
        self._node_factory = NoteBookNodeFactory()
        self._conn = NoteBookConnection(self, self._node_factory)
        self.pref = NoteBookPreferences()

        rootdir = keepnote.ensure_unicode(rootdir, keepnote.FS_ENCODING)
        if rootdir is not None:
            self._attr["title"] = os.path.basename(rootdir)
        else:
            self._attr["title"] = None
        self._basename = rootdir
        self._dirty = set()
        self._trash = None
        self._index = None
        self.attr_defs ={}
        self._necessary_attrs = []
        
        self._attr["order"] = 0

        # init notebook attributes
        self._init_default_attr()

        # init trash
        if rootdir:
            self._trash_path = get_trash_dir(self.get_path())
        else:
            self._trash_path = None
        
        # listeners
        self.node_changed = Listeners()  # signature = (node, recurse)
        self.closing_event = Listeners()
        self.close_event = Listeners()

        # add node types
        self._init_default_node_types()


    def _set_basename(self, path):
        """Sets the basename directory of the node"""
        self._basename = path


    def _init_default_attr(self):
        """Initialize default notebook attributes"""
        
        self._necessary_attrs = ["nodeid", "created_time", "modified_time"]
        self.clear_attr_defs()
        for attr in g_default_attr_defs:
            self.add_attr_def(attr)
        
        
    def _init_default_node_types(self):
        """Initialize default node types for notebook"""
        
        self._node_factory.clear()
        self._node_factory.add_node_type(
            CONTENT_TYPE_DIR,
            lambda parent, notebook, attr:
            NoteBookDir(parent=parent,
                        notebook=notebook))
        self._node_factory.add_node_type(
            CONTENT_TYPE_PAGE,
            lambda parent, notebook, attr:
            NoteBookPage(parent=parent,
                         notebook=notebook))
        self._node_factory.add_node_type(
            CONTENT_TYPE_TRASH,
            lambda parent, notebook, attr:
            NoteBookTrash(TRASH_NAME, notebook))


    def add_attr_def(self, attr):
        """Adds a new attribute definition to the notebook"""
        self.attr_defs[attr.key] = attr
    
    def clear_attr_defs(self):
        """Clears all attribute definitions from the notebook"""
        self.attr_defs.clear()

    def get_children(self):
        """Returns all children of this node"""

        # ensure trash folder exists
        if self._children is None:
            self._get_children()        
            self._init_trash()
        
        return self._children


    #===================================================
    # input/output
    
    def create(self):
        """Initialize NoteBook on the file-system"""
        
        # TODO: replace with conn
        NoteBookDir.create(self)
        os.mkdir(self.get_pref_dir())
        os.mkdir(self.get_icon_dir())
        self.write_meta_data()
        self.write_preferences()

        # init index database
        self._init_index()

    
    def load(self, filename=None):
        """Load the NoteBook from the file-system"""

        # ensure filename points to notebook directory
        if filename is not None:
            filename = normalize_notebook_dirname(filename, longpath=False)
            self._set_basename(filename)
        
        # read basic info
        self._trash_path = get_trash_dir(self.get_path())
        self.read_meta_data()
        self.read_preferences()
        self._init_index()

        self.notify_change(True)
    
    
    def save(self, force=False):
        """Recursively save any loaded nodes"""

        if force or self in self._dirty:
            self.write_meta_data()            
            self.write_preferences()
        self._set_dirty(False)

        if force:
            for node in self.get_children():
                node.save(force=force)
        else:
            for node in list(self._dirty):
                node.save()
        self._index.save()
        
        self._dirty.clear()


    def _init_index(self):
        """Initialize the index"""
        self._index = notebook_index.NoteBookIndex(self)
        self._index.add_attr(notebook_index.AttrIndex("icon", "TEXT"))
        self._index.add_attr(notebook_index.AttrIndex("title", "TEXT",
                                                      index_value=True))

        


    def _set_dirty_node(self, node, dirty):
        """Mark a node to be dirty (needs saving) in NoteBook"""        
        if dirty:
            self._dirty.add(node)
        else:
            if node in self._dirty:
                self._dirty.remove(node)
    
    
    def _is_dirty_node(self, node):
        """Returns True if node is dirty (needs saving)"""
        return node in self._dirty
        
    
    def save_needed(self):
        """Returns True if save is needed"""
        return len(self._dirty) > 0



    def read_node(self, parent, path):
        """Read a NoteBookNode"""
        return self._conn.read_node(parent, path)


    def new_node(self, content_type, path, parent, attr):
        """Create a new NodeBookNode"""        
        node = self._node_factory.new_node(content_type, path,
                                           parent, self, attr)
        return node


    def write_meta_data(self):
        self._conn.write_node_meta_data(self)

    def read_meta_data(self):
        self._conn.read_node_meta_data(self)

    def write_node_meta_data(self, node):
        self._conn.write_node_meta_data(node)

    def read_node_meta_data(self, node):
        self._conn.read_node_meta_data(node)
        


    #=====================================
    # attrs

    def get_necessary_attrs(self):
        return self._necessary_attrs


    #=====================================
    # trash functions

    def get_trash(self):
        """Returns the Trash Folder for the NoteBook"""
        return self._trash        


    def _init_trash(self):
        """Ensures Trash directory exists in a notebook"""
        
        # ensure trash directory exists
        self._trash = None
        for child in self._children:
            if self.is_trash_dir(child):
                self._trash = child
                break
        
        # if no trash folder, create it
        if self._trash is None:
            try:
                self._trash = NoteBookTrash(TRASH_NAME, self)
                self._trash.create()
                self._add_child(self._trash)

            except NoteBookError, e:
                raise NoteBookError(_("Cannot create Trash folder"), e)


    
    
    def is_trash_dir(self, child):
        """Returns True if child node is the Trash Folder"""
        return child.get_attr("content_type") == CONTENT_TYPE_TRASH


    def empty_trash(self):
        """Deletes all nodes under Trash Folder"""

        if self._trash is None:
            self._init_trash()

        for child in reversed(list(self._trash.get_children())):
            child.delete()

    #==============================================
    # icons

    # TODO: think about how to replace icon interface with connection
    # this may not be necessary

    def get_icon_file(self, basename):
        """Lookup icon filename in notebook icon store"""

        filename = self._conn.path_join(
            NOTEBOOK_META_DIR, NOTEBOOK_ICON_DIR, basename)
        if self._conn.isfile(self, filename):
            return self._conn.get_node_file(self, filename)
        else:
            return None


    def get_icons(self):
        """Returns list of icons in notebook icon store"""
        filename = self._conn.path_join(
            NOTEBOOK_META_DIR, NOTEBOOK_ICON_DIR)
        filenames = list(self._conn.node_listdir(self, filename))
        filenames.sort()
        return filenames


    def install_icon(self, filename):
        """Installs an icon into the notebook icon store"""

        # TODO: test this function

        basename = os.path.basename(filename)
        basename, ext = os.path.splitext(basename)
        newfilename = self._conn.path_join(NOTEBOOK_META_DIR, NOTEBOOK_ICON_DIR,
                                           basename)

        newfilename = self._conn.new_filename(self, newfilename, ext, "-",
                                              ensure_valid=False)

        self._conn.copy_node_file(None, filename, self, newfilename)
        return self._conn.path_basename(newfilename)



    def install_icons(self, filename, filename_open):
        """Installs an icon into the notebook icon store"""

        # TODO: test this function

        basename = os.path.basename(filename)
        basename, ext = os.path.splitext(basename)
        startname = self._conn.path_join(NOTEBOOK_META_DIR, NOTEBOOK_ICON_DIR,
                                         basename)

        nodepath = self.get_path()

        number = 2
        use_number = False
        while True:
            newfilename, number = self._conn.new_filename(
                self, startname, ext, "-",
                number=number, return_number=True, use_number=use_number,
                ensure_valid=False,
                path=nodepath)

            # determine open icon filename
            newfilename_open = startname
            if number:
                newfilename_open += "-" + str(number)
            else:
                number = 2
            newfilename_open += "-open" + ext

            # see if it already exists
            if self._conn.path_exists(self, newfilename_open, path=nodepath):
                number += 1
                use_number = True
            else:
                # we are done searching for names
                break
            
        self._conn.copy_node_file(None, filename, self, newfilename)
        self._conn.copy_node_file(None, filename_open, self, newfilename_open)

        return (self._conn.path_basename(newfilename), 
                self._conn.path_basename(newfilename_open))


    def uninstall_icon(self, basename):
        """Removes an icon from the notebook icon store"""
        if len(basename) == 0:
            return
        filename = self._conn.path_join(
            NOTEBOOK_META_DIR, NOTEBOOK_ICON_DIR, basename)
        self._conn.remove_node_file(self, filename)
        
        #filename = self.get_icon_file(basename)
        #if filename:
        #    os.remove(filename)
    
    
    def get_universal_root_id(self):
        return UNIVERSAL_ROOT
    
    
    #================================================
    # search

    def get_node_by_id(self, nodeid):
        """Lookup node by nodeid"""

        # TODO: could make this more efficient by not loading all uncles

        path = self._index.get_node_path(nodeid)
        if path is None:
            return None
        
        def walk(node, path):
            if len(path) == 0:
                return node

            # search children
            basename = path[0]
            for child in node.get_children():
                if child.get_basename() == basename:
                    return walk(child, path[1:])
            
            # node not found
            return None
        return walk(self, path[1:])
    
    
    def get_node_path_by_id(self, nodeid):
        """Lookup node by nodeid"""
        
        path = self._index.get_node_path(nodeid)
        if path is None:
            return None
        
        return os.path.join(self.get_path(), *path[1:])


    def search_node_titles(self, text):
        """Search nodes by title"""
        return self._index.search_titles(text)


    def close(self, save=True):
        """Close notebook"""
        
        self.closing_event.notify(self, save)
        if save:
            self.save()
        self._index.close()
        self.close_event.notify(self)


    #===============================================
    # preferences
    
    def get_pref_file(self):
        """Gets the NoteBook's preference file"""
        return self._conn.get_node_file(self, PREF_FILE)
    
    def get_pref_dir(self):
        """Gets the NoteBook's preference directory"""
        return self._conn.get_node_file(self, NOTEBOOK_META_DIR)

    def get_icon_dir(self):
        """Gets the NoteBook's icon directory"""
        return self._conn.get_node_file(
            self, self._conn.path_join(NOTEBOOK_META_DIR, NOTEBOOK_ICON_DIR))
    

    def set_preferences_dirty(self):
        """Notifies notebook that preferences need saving"""
        self._set_dirty(True)

    
    def write_preferences(self):
        """Writes the NoteBooks preferences to the file-system"""
        try:
            # ensure preference directory exists
            self._conn.mkdir(self, NOTEBOOK_META_DIR)
                
            # ensure icon directory exists
            self._conn.mkdir(
                self, self._conn.path_join(NOTEBOOK_META_DIR, 
                                           NOTEBOOK_ICON_DIR))

            data = self.pref.get_data()

            out = self.open_file(PREF_FILE, "w", codec="utf-8")
            out.write(u'<?xml version="1.0" encoding="UTF-8"?>\n'
                      u'<notebook>\n'
                      u'<version>%d</version>\n'
                      u'<pref>\n' % data["version"])
            plist.dump(data, out, indent=4, depth=4)
            out.write(u'</pref>\n'
                      u'</notebook>\n')
            out.close()

        except (IOError, OSError), e:
            raise NoteBookError(_("Cannot save notebook preferences"), e)
        except Exception, e:
            raise NoteBookError(_("File format error"), e)

    
    def read_preferences(self):
        """Reads the NoteBook's preferneces from the file-system"""
        
        try:
            infile = self.open_file(PREF_FILE, "r", codec="utf-8")
            #tree = ElementTree.parse(infile)
            #root = tree.getroot()
            root = ET.fromstring(infile.read())
            tree = ET.ElementTree(root)
        except IOError, e:
            raise NoteBookError(_("Cannot read notebook preferences"), e)
        except Exception, e:
            raise NoteBookError(_("Notebook preference data is corrupt"), e)
        finally:
            infile.close()


        # check version
        version = get_notebook_version_etree(tree)
        if version > NOTEBOOK_FORMAT_VERSION:
            raise NoteBookVersionError(version,
                                       NOTEBOOK_FORMAT_VERSION)

        
        if root.tag == "notebook":
            p = root.find("pref")
            if p is not None:
                d = p.find("dict")
                if d is not None:
                    data = plist.load_etree(d)
                else:
                    data = orderdict.OrderDict()
            else:
                data = orderdict.OrderDict()
        
        data["version"] = version
        self.pref.set_data(data)
      

        
#=============================================================================
# Filesystem interface

# TODO: think about how "mounts" should work


class NoteBookConnection (object):
    def __init__(self, notebook, node_factory):
        self._notebook = notebook
        self._node_factory = node_factory
    

    #================================
    # path API

    def get_node_path(self, node):
        """Returns the path key of the node"""
        
        if node._basename is None:
            return None

        # TODO: think about multiple parents
        path_list = []
        ptr = node
        while ptr is not None:
            path_list.append(ptr._basename)
            ptr = ptr._parent
        path_list.reverse()
        
        return os.path.join(* path_list)


    def get_node_name_path(self, node):
        """Returns list of basenames from root to node"""

        if node._basename is None:
            return None

        # TODO: think about multiple parents
        path_list = []
        ptr = node
        while ptr is not None:
            path_list.append(ptr._basename)
            ptr = ptr._parent
        path_list.pop()
        path_list.reverse()
        return path_list
    
    
    def set_node_basename(self, node, path):
        """Sets the basename directory of the node"""
        
        if node._parent is None:
            # the root node can take a multiple directory path
            node._basename = path
        elif path is None:
            node._basename = None
        else:
            # non-root nodes can only take the last directory as a basename
            node._basename = os.path.basename(path)




    #===============
    # file API

    def path_join(self, *parts):
        return os.path.join(*parts)

    def get_node_file(self, node, filename, path=None):
        if path is None:
            path = self.get_node_path(node)
        return os.path.join(path, filename)


    def open_node_file(self, node, filename, mode="r", codec=None, path=None):
        """Open a file contained within a node"""
        if path is None:
            path = self.get_node_path(node)
        return safefile.open(
            os.path.join(path, filename), mode, codec=codec)

    def remove_node_file(self, node, filename, path=None):
        """Open a file contained within a node"""
        if path is None:
            path = self.get_node_path(node)
        os.remove(os.path.join(path, filename))


    def new_filename(self, node, new_filename, ext=u"", sep=u" ", number=2, 
                     return_number=False, use_number=False, ensure_valid=True,
                     path=None):
        if path is None:
            path = self.get_node_path(node)
        if ext is None:
            new_filename, ext = os.path.splitext(new_filename)

        basename = os.path.basename(new_filename)
        path2 = os.path.join(path, os.path.dirname(new_filename))

        if ensure_valid:
            fullname = get_valid_unique_filename(
                path2, basename, ext, sep=sep, number=number)
        else:
            if return_number:
                fullname, number = get_unique_filename(
                    path2, basename, ext, sep=sep, number=number,
                    return_number=return_number, use_number=use_number)
            else:
                fullname = get_unique_filename(
                    path2, basename, ext, sep=sep, number=number,
                    return_number=return_number, use_number=use_number)

        if return_number:
            return relpath(fullname, path), number
        else:
            return relpath(fullname, path)



    def mkdir(self, node, filename, path=None):
        if path is None:
            path = self.get_node_path(node)
        fullname = os.path.join(path, filename)
        if not os.path.exists(fullname):
            os.mkdir(fullname)

    
    def isfile(self, node, filename, path=None):
        if path is None:
            path = self.get_node_path(node)
        return os.path.isfile(os.path.join(path, filename))


    def path_exists(self, node, filename, path=None):
        if path is None:
            path = self.get_node_path(node)
        return os.path.exists(os.path.join(path, filename))


    def path_basename(self, filename):
        return os.path.basename(filename)

        
    def node_listdir(self, node, filename=None, path=None):
        """
        List data files in node
        """

        if path is None:
            path = self.get_node_path(node)
        if filename is not None:
            path = os.path.join(path, filename)
        
        for filename in os.listdir(path):
            if (filename != NODE_META_FILE and 
                not filename.startswith("__")):
                fullname = os.path.join(path, filename)
                if not os.path.exists(get_node_meta_file(fullname)):
                    # ensure directory is not a node
                    yield filename

    
    def copy_node_files(self, node1, node2):
        """
        Copy all data files from node1 to node2
        """
        
        path1 = self.get_node_path(node1)
        path2 = self.get_node_path(node2)

        for filename in self.node_listdir(node1, path1):
            fullname1 = os.path.join(path1, filename)
            fullname2 = os.path.join(path2, filename)
            
            if os.path.isfile(fullname1):
                shutil.copy(fullname1, fullname2)
            elif os.path.isdir(fullname1):
                shutil.copytree(fullname1, fullname2)

    
    def copy_node_file(self, node1, filename1, node2, filename2,
                       path1=None, path2=None):
        """
        Copy a file between two nodes

        if node is None, filename is assumed to be a local file
        """

        if node1 is None:
            fullname1 = filename1
        else:
            if path1 is None:
                path1 = self.get_node_path(node1)
            fullname1 = os.path.join(path1, filename1)

        if node2 is None:
            fullname2 = filename2
        else:
            if path2 is None:
                path2 = self.get_node_path(node2)
            fullname2 = os.path.join(path2, filename2)
        
        if os.path.isfile(fullname1):
            shutil.copy(fullname1, fullname2)
        elif os.path.isdir(fullname1):
            shutil.copytree(fullname1, fullname2)
        


    #======================
    # Node I/O API

    def read_node(self, parent, path):
        """
        Reads a node from disk

        Returns None if not a node directory
        """
        
        metafile = get_node_meta_file(path)
        attr = self._read_meta_data(metafile, self._notebook.attr_defs)
        return self._node_factory.new_node(
            attr.get("content_type", CONTENT_TYPE_DIR),
            path, parent, self._notebook, attr)



    def read_node_meta_data(self, node):
        """Read a node meta data file"""
        node.set_meta_data(
            self._read_meta_data(node.get_meta_file(), 
                                 self._notebook.attr_defs))

    def write_node_meta_data(self, node):
        """Write a node meta data file"""
        self._write_meta_data(node.get_meta_file(), node, 
                              self._notebook.attr_defs)
    

    def _write_meta_data(self, filename, node, attr_defs):
        """Write a node meta data file"""
        
        try:
            out = safefile.open(filename, "w", codec="utf-8")
            out.write(XML_HEADER)
            out.write("<node>\n"
                      "<version>%s</version>\n" % node.get_version())
            
            for key, val in node.iter_attr():
                attr = attr_defs.get(key, None)
                
                if attr is not None:
                    out.write('<attr key="%s">%s</attr>\n' %
                              (key, escape(attr.write(val))))
                elif key == "version":
                    # skip version attr
                    pass
                elif isinstance(val, UnknownAttr):
                    # write unknown attrs if they are strings
                    out.write('<attr key="%s">%s</attr>\n' %
                              (key, escape(val.value)))
                else:
                    # drop attribute
                    pass
                
            out.write("</node>\n")
            out.close()
        except Exception, e:
            raise NoteBookError(_("Cannot write meta data"), e)



    def _read_meta_data(self, filename, attr_defs):
        """Read a node meta data file"""
        
        attr = {}

        try:
            tree = ET.ElementTree(file=filename)
        except Exception, e:
            raise NoteBookError(_("Error reading meta data file"), e)

        # check root
        root = tree.getroot()
        if root.tag != "node":
            raise NoteBookError(_("Root tag is not 'node'"))
        
        # iterate children
        for child in root:
            if child.tag == "version":
                attr["version"] = int(child.text)
            elif child.tag == "attr":
                key = child.get("key", None)
                if key is not None:
                    attr_parser = attr_defs.get(key, None)
                    if attr_parser is not None:
                        attr[key] = attr_parser.read(child.text)
                    else:
                        # unknown attribute is read as a UnknownAttr
                        attr[key] = UnknownAttr(child.text)

        return attr


    def create_node(self, node, path=None):

        if path is None:
            path = self.get_node_path(node)
        if path is None:
            # use title to set path
            parent_path = node.get_parent().get_path()
            path = get_valid_unique_filename(
                parent_path, node.get_attr("title", _("New Page")))
            self.set_node_basename(node, path)

        try:
            os.mkdir(path)
            self.write_node_meta_data(node)
        except OSError, e:
            raise NoteBookError(_("Cannot create node"), e)

    def delete_node(self, node):
        try:
            shutil.rmtree(node.get_path())
        except OSError, e:
            raise NoteBookError(_("Do not have permission to delete"), e)
        

    def move_node(self, node, new_parent):
        
        old_path = self.get_node_path(node)
        new_parent_path = self.get_node_path(new_parent)
        new_path = get_valid_unique_filename(
            new_parent_path, node.get_attr("title", _("New Page")))

        try:
            os.rename(old_path, new_path)
        except OSError, e:
            raise NoteBookError(_("Do not have permission for move"), e)

        return new_path

    def rename_node(self, node, title):
        
        # try to pick a path that closely resembles the title
        path = self.get_node_path(node)
        parent_path = os.path.dirname(path)
        path2 = get_valid_unique_filename(parent_path, title)

        try:
            os.rename(path, path2)
        except OSError, e:
            raise NoteBookError(_("Cannot rename '%s' to '%s'" % (path, path2)), e)
        
        return path2


    def node_list_children(self, node, path=None):
        if path is None:
            path = self.get_node_path(node)
            assert path is not None, node
        
        try:
            files = os.listdir(path)
        except OSError, e:
            raise NoteBookError(_("Do not have permission to read folder contents: %s") % path, e)
        
        for filename in files:
            path2 = os.path.join(path, filename)
            if os.path.exists(get_node_meta_file(path2)):
                yield path2


#=============================================================================
# Meta Data Parsing


class NoteBookNodeFactory (object):
    """
    This is a factory class that creates NoteBookNode's.  
    """

    def __init__(self):
        self._makers = {}

    def clear(self):
        self._makers.clear()

    def add_node_type(self, content_type, make_func):
        """
        Adds a new node content_type to the factory.
        Enables factory to build nodes of the given type by calling the
        given function 'make_func'.

        make_func must have the signature:
           make_func(path, parent, notebook, attr_dict)
        """
        
        self._makers[content_type] = make_func
        

    def new_node(self, content_type, path, parent, notebook, attr):
        """Creates a new node given a content_type"""
        
        maker = self._makers.get(content_type, None)
        if maker:
            node = maker(parent, notebook, attr)
            node._set_basename(path)
            node.set_meta_data(attr)
            return node
        
        elif "payload_filename" in attr:
            # test for generic file
            node = NoteBookGenericFile(filename=attr["payload_filename"],
                                       title=attr.get("title", _("New File")),
                                       content_type=content_type,
                                       parent=parent, notebook=notebook)
            node._set_basename(path)
            node.set_meta_data(attr)
            return node
        
        else:
            # return unintialized generic file
            node = NoteBookGenericFile(title=attr.get("title", _("New File")),
                                       content_type=content_type,
                                       parent=parent, notebook=notebook)
            node._set_basename(path)
            node.set_meta_data(attr)
            return node

   
