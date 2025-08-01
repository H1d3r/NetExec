import binascii
import json
import datetime
from enum import Enum
from impacket.ldap import ldaptypes
from impacket.uuid import bin_to_string
from nxc.helpers.msada_guids import SCHEMA_OBJECTS, EXTENDED_RIGHTS
from nxc.parsers.ldap_results import parse_result_attributes
from ldap3.utils.conv import escape_filter_chars
from ldap3.protocol.microsoft import security_descriptor_control
import sys
import traceback
from os.path import isfile

OBJECT_TYPES_GUID = {}
OBJECT_TYPES_GUID.update(SCHEMA_OBJECTS)
OBJECT_TYPES_GUID.update(EXTENDED_RIGHTS)

# Universal SIDs
WELL_KNOWN_SIDS = {
    "S-1-0": "Null Authority",
    "S-1-0-0": "Nobody",
    "S-1-1": "World Authority",
    "S-1-1-0": "Everyone",
    "S-1-2": "Local Authority",
    "S-1-2-0": "Local",
    "S-1-2-1": "Console Logon",
    "S-1-3": "Creator Authority",
    "S-1-3-0": "Creator Owner",
    "S-1-3-1": "Creator Group",
    "S-1-3-2": "Creator Owner Server",
    "S-1-3-3": "Creator Group Server",
    "S-1-3-4": "Owner Rights",
    "S-1-5-80-0": "All Services",
    "S-1-4": "Non-unique Authority",
    "S-1-5": "NT Authority",
    "S-1-5-1": "Dialup",
    "S-1-5-2": "Network",
    "S-1-5-3": "Batch",
    "S-1-5-4": "Interactive",
    "S-1-5-6": "Service",
    "S-1-5-7": "Anonymous",
    "S-1-5-8": "Proxy",
    "S-1-5-9": "Enterprise Domain Controllers",
    "S-1-5-10": "Principal Self",
    "S-1-5-11": "Authenticated Users",
    "S-1-5-12": "Restricted Code",
    "S-1-5-13": "Terminal Server Users",
    "S-1-5-14": "Remote Interactive Logon",
    "S-1-5-15": "This Organization",
    "S-1-5-17": "This Organization",
    "S-1-5-18": "Local System",
    "S-1-5-19": "NT Authority",
    "S-1-5-20": "NT Authority",
    "S-1-5-32-544": "Administrators",
    "S-1-5-32-545": "Users",
    "S-1-5-32-546": "Guests",
    "S-1-5-32-547": "Power Users",
    "S-1-5-32-548": "Account Operators",
    "S-1-5-32-549": "Server Operators",
    "S-1-5-32-550": "Print Operators",
    "S-1-5-32-551": "Backup Operators",
    "S-1-5-32-552": "Replicators",
    "S-1-5-64-10": "NTLM Authentication",
    "S-1-5-64-14": "SChannel Authentication",
    "S-1-5-64-21": "Digest Authority",
    "S-1-5-80": "NT Service",
    "S-1-5-83-0": "NT VIRTUAL MACHINE\\Virtual Machines",
    "S-1-16-0": "Untrusted Mandatory Level",
    "S-1-16-4096": "Low Mandatory Level",
    "S-1-16-8192": "Medium Mandatory Level",
    "S-1-16-8448": "Medium Plus Mandatory Level",
    "S-1-16-12288": "High Mandatory Level",
    "S-1-16-16384": "System Mandatory Level",
    "S-1-16-20480": "Protected Process Mandatory Level",
    "S-1-16-28672": "Secure Process Mandatory Level",
    "S-1-5-32-554": "BUILTIN\\Pre-Windows 2000 Compatible Access",
    "S-1-5-32-555": "BUILTIN\\Remote Desktop Users",
    "S-1-5-32-557": "BUILTIN\\Incoming Forest Trust Builders",
    "S-1-5-32-556": "BUILTIN\\Network Configuration Operators",
    "S-1-5-32-558": "BUILTIN\\Performance Monitor Users",
    "S-1-5-32-559": "BUILTIN\\Performance Log Users",
    "S-1-5-32-560": "BUILTIN\\Windows Authorization Access Group",
    "S-1-5-32-561": "BUILTIN\\Terminal Server License Servers",
    "S-1-5-32-562": "BUILTIN\\Distributed COM Users",
    "S-1-5-32-569": "BUILTIN\\Cryptographic Operators",
    "S-1-5-32-573": "BUILTIN\\Event Log Readers",
    "S-1-5-32-574": "BUILTIN\\Certificate Service DCOM Access",
    "S-1-5-32-575": "BUILTIN\\RDS Remote Access Servers",
    "S-1-5-32-576": "BUILTIN\\RDS Endpoint Servers",
    "S-1-5-32-577": "BUILTIN\\RDS Management Servers",
    "S-1-5-32-578": "BUILTIN\\Hyper-V Administrators",
    "S-1-5-32-579": "BUILTIN\\Access Control Assistance Operators",
    "S-1-5-32-580": "BUILTIN\\Remote Management Users",
}


# GUID rights enum
# GUID thats permits to identify extended rights in an ACE
# https://docs.microsoft.com/en-us/windows/win32/adschema/a-rightsguid
class RIGHTS_GUID(Enum):
    WriteMembers = "bf9679c0-0de6-11d0-a285-00aa003049e2"
    ResetPassword = "00299570-246d-11d0-a768-00aa006e0529"
    DS_Replication_Get_Changes = "1131f6aa-9c07-11d1-f79f-00c04fc2dcd2"
    DS_Replication_Get_Changes_All = "1131f6ad-9c07-11d1-f79f-00c04fc2dcd2"


# ACE flags enum
# New ACE at the end of SACL for inheritance and access return system-audit
# https://docs.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-addauditaccessobjectace
class ACE_FLAGS(Enum):
    CONTAINER_INHERIT_ACE = ldaptypes.ACE.CONTAINER_INHERIT_ACE
    FAILED_ACCESS_ACE_FLAG = ldaptypes.ACE.FAILED_ACCESS_ACE_FLAG
    INHERIT_ONLY_ACE = ldaptypes.ACE.INHERIT_ONLY_ACE
    INHERITED_ACE = ldaptypes.ACE.INHERITED_ACE
    NO_PROPAGATE_INHERIT_ACE = ldaptypes.ACE.NO_PROPAGATE_INHERIT_ACE
    OBJECT_INHERIT_ACE = ldaptypes.ACE.OBJECT_INHERIT_ACE
    SUCCESSFUL_ACCESS_ACE_FLAG = ldaptypes.ACE.SUCCESSFUL_ACCESS_ACE_FLAG


# ACE flags enum
# For an ACE, flags that indicate if the ObjectType and the InheritedObjecType are set with a GUID
# Since these two flags are the same for Allowed and Denied access, the same class will be used from 'ldaptypes'
# https://docs.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-access_allowed_object_ace
class OBJECT_ACE_FLAGS(Enum):
    ACE_OBJECT_TYPE_PRESENT = ldaptypes.ACCESS_ALLOWED_OBJECT_ACE.ACE_OBJECT_TYPE_PRESENT
    ACE_INHERITED_OBJECT_TYPE_PRESENT = ldaptypes.ACCESS_ALLOWED_OBJECT_ACE.ACE_INHERITED_OBJECT_TYPE_PRESENT


# Access Mask enum
# Access mask permits to encode principal's rights to an object. This is the rights the principal behind the specified SID has
# https://docs.microsoft.com/en-us/openspecs/windows_protocols/ms-dtyp/7a53f60e-e730-4dfe-bbe9-b21b62eb790b
# https://docs.microsoft.com/en-us/windows/win32/api/iads/ne-iads-ads_rights_enum?redirectedfrom=MSDN
class ACCESS_MASK(Enum):
    # Generic Rights
    GenericRead = 0x80000000  # ADS_RIGHT_GENERIC_READ
    GenericWrite = 0x40000000  # ADS_RIGHT_GENERIC_WRITE
    GenericExecute = 0x20000000  # ADS_RIGHT_GENERIC_EXECUTE
    GenericAll = 0x10000000  # ADS_RIGHT_GENERIC_ALL

    # Maximum Allowed access type
    MaximumAllowed = 0x02000000

    # Access System Acl access type
    AccessSystemSecurity = 0x01000000  # ADS_RIGHT_ACCESS_SYSTEM_SECURITY

    # Standard access types
    Synchronize = 0x00100000  # ADS_RIGHT_SYNCHRONIZE
    WriteOwner = 0x00080000  # ADS_RIGHT_WRITE_OWNER
    WriteDACL = 0x00040000  # ADS_RIGHT_WRITE_DAC
    ReadControl = 0x00020000  # ADS_RIGHT_READ_CONTROL
    Delete = 0x00010000  # ADS_RIGHT_DELETE

    # Specific rights
    AllExtendedRights = 0x00000100  # ADS_RIGHT_DS_CONTROL_ACCESS
    ListObject = 0x00000080  # ADS_RIGHT_DS_LIST_OBJECT
    DeleteTree = 0x00000040  # ADS_RIGHT_DS_DELETE_TREE
    WriteProperties = 0x00000020  # ADS_RIGHT_DS_WRITE_PROP
    ReadProperties = 0x00000010  # ADS_RIGHT_DS_READ_PROP
    Self = 0x00000008  # ADS_RIGHT_DS_SELF
    ListChildObjects = 0x00000004  # ADS_RIGHT_ACTRL_DS_LIST
    DeleteChild = 0x00000002  # ADS_RIGHT_DS_DELETE_CHILD
    CreateChild = 0x00000001  # ADS_RIGHT_DS_CREATE_CHILD


# Simple permissions enum
# Simple permissions are combinaisons of extended permissions
# https://docs.microsoft.com/en-us/previous-versions/windows/it-pro/windows-server-2003/cc783530(v=ws.10)?redirectedfrom=MSDN
class SIMPLE_PERMISSIONS(Enum):
    FullControl = 0xF01FF
    Modify = 0x0301BF
    ReadAndExecute = 0x0200A9
    ReadAndWrite = 0x02019F
    Read = 0x20094
    Write = 0x200BC


# Mask ObjectType field enum
# Possible values for the Mask field in object-specific ACE (permitting to specify extended rights in the ObjectType field for example)
# Since these flags are the same for Allowed and Denied access, the same class will be used from 'ldaptypes'
# https://docs.microsoft.com/en-us/openspecs/windows_protocols/ms-dtyp/c79a383c-2b3f-4655-abe7-dcbb7ce0cfbe
class ALLOWED_OBJECT_ACE_MASK_FLAGS(Enum):
    ControlAccess = ldaptypes.ACCESS_ALLOWED_OBJECT_ACE.ADS_RIGHT_DS_CONTROL_ACCESS
    CreateChild = ldaptypes.ACCESS_ALLOWED_OBJECT_ACE.ADS_RIGHT_DS_CREATE_CHILD
    DeleteChild = ldaptypes.ACCESS_ALLOWED_OBJECT_ACE.ADS_RIGHT_DS_DELETE_CHILD
    ReadProperty = ldaptypes.ACCESS_ALLOWED_OBJECT_ACE.ADS_RIGHT_DS_READ_PROP
    WriteProperty = ldaptypes.ACCESS_ALLOWED_OBJECT_ACE.ADS_RIGHT_DS_WRITE_PROP
    Self = ldaptypes.ACCESS_ALLOWED_OBJECT_ACE.ADS_RIGHT_DS_SELF


SEARCH_FILTERS = {
    "TARGET": lambda target: f"(sAMAccountName={escape_filter_chars(target)})",
    "TARGET_DN": lambda target: f"(distinguishedName={escape_filter_chars(target)})"
}


class NXCModule:
    """Module to read and backup the Discretionary Access Control List of one or multiple objects.

    This module is essentially inspired from the dacledit.py script of Impacket that we have coauthored, @_nwodtuhs and me.
    It has been converted to an LDAPConnection session, and improvements on the filtering and the ability to specify multiple targets have been added.
    It could be interesting to implement the write/remove functions here, but a ldap3 session instead of a LDAPConnection one is required to write.
    """

    name = "daclread"
    description = "Read and backup the Discretionary Access Control List of objects. Be careful, this module cannot read the DACLS recursively, see more explanation in the options."
    supported_protocols = ["ldap"]

    def __init__(self, context=None, module_options=None):
        self.context = context
        self.module_options = module_options

        # Initialize module variables
        self.principal_sAMAccountName = None
        self.principal_sid = None
        self.action = "read"
        self.ace_type = "allowed"
        self.rights = None
        self.rights_guid = None

    def options(self, context, module_options):
        """
        Be careful, this module cannot read the DACLS recursively. 
        For example, if an object has particular rights because it belongs to a group, the module will not be able to see it directly, you have to check the group rights manually.

        TARGET          The objects that we want to read or backup the DACLs, specified by its SamAccountName
        TARGET_DN       The object that we want to read or backup the DACL, specified by its DN (useful to target the domain itself)
        PRINCIPAL       The trustee that we want to filter on
        ACTION          The action to realise on the DACL (read, backup)
        ACE_TYPE        The type of ACE to read (Allowed or Denied)
        RIGHTS          An interesting right to filter on ('FullControl', 'ResetPassword', 'WriteMembers', 'DCSync')
        RIGHTS_GUID     A right GUID that specify a particular rights to filter on

        Based on the work of @_nwodtuhs and @BlWasp_.
        """
        context.log.debug(f"module_options: {module_options}")

        if not module_options:
            context.log.fail("Select an option, example: -M daclread -o TARGET=Administrator ACTION=read")
            sys.exit(1)

        self.targets = []
        self.target_SID = None

        for option in "TARGET", "TARGET_DN":
            if option in module_options:
                context.log.debug("There is a target specified!")
                if isfile(module_options[option]):
                    try:
                        target_file = open(module_options[option])  # noqa: SIM115
                        for line in target_file:
                            context.log.debug(f"Adding target from file: {line}")
                            self.targets.append((line.strip(), SEARCH_FILTERS[option]))
                    except Exception:
                        context.log.fail("The file doesn't exist or cannot be opened.")
                else:
                    context.log.debug(f"Adding target: {module_options[option]}")
                    self.targets.append((module_options[option].strip(), SEARCH_FILTERS[option]))

        if not self.targets:
            context.log.fail("No target specified, please specify at least one target with the TARGET or TARGET_DN options.")
            sys.exit(1)

        if "PRINCIPAL" in module_options:
            self.principal_sAMAccountName = module_options["PRINCIPAL"]

        if "ACTION" in module_options:
            self.action = module_options["ACTION"]

        if "ACE_TYPE" in module_options:
            self.ace_type = module_options["ACE_TYPE"]
            
        if "RIGHTS" in module_options:
            self.rights = module_options["RIGHTS"]

        if "RIGHTS_GUID" in module_options:
            self.rights_guid = module_options["RIGHTS_GUID"]

    def on_login(self, context, connection):
        """On a successful LDAP login we perform a search for the targets' SID, their Security Descriptors and the principal's SID if there is one specified"""
        context.log.highlight("Be careful, this module cannot read the DACLS recursively.")
        self.context = context
        self.connection = connection

        # Searching for the principal SID
        if self.principal_sAMAccountName is not None:
            try:
                resp = connection.search(
                    searchFilter=f"(sAMAccountName={escape_filter_chars(self.principal_sAMAccountName)})",
                    attributes=["objectSid"],
                )
                resp_parsed = parse_result_attributes(resp)[0]
                self.principal_sid = resp_parsed["objectSid"]
                context.log.highlight(f"Found principal SID to filter on: {self.principal_sid}")
            except Exception as e:
                context.log.fail(f"Principal SID not found in LDAP ({self.principal_sAMAccountName})")
                context.log.debug(f"Exception: {e}, {traceback.format_exc()}")
                return

        # Searching for the targets SID and their Security Descriptors
        for target, search_filter in self.targets:
            try:
                # Searching for target account with its security descriptor
                resp = connection.search(
                    searchFilter=search_filter(target),
                    attributes=["distinguishedName", "nTSecurityDescriptor"],
                    searchControls=security_descriptor_control(sdflags=0x04),
                )
                resp_parsed = parse_result_attributes(resp)[0]

                # Extract security descriptor data
                target_principal_dn = resp_parsed["distinguishedName"]
                principal_raw_security_descriptor = resp_parsed["nTSecurityDescriptor"]
                principal_security_descriptor = ldaptypes.SR_SECURITY_DESCRIPTOR(data=principal_raw_security_descriptor)
                context.log.highlight(f"Target principal found in LDAP ({target_principal_dn})")
            except Exception as e:
                context.log.fail(f"Target SID not found in LDAP ({target})")
                context.log.debug(f"Exception: {e}, {traceback.format_exc()}")
                continue

            if self.action == "read":
                self.read(principal_security_descriptor)
            if self.action == "backup":
                self.backup(target, target_principal_dn, principal_raw_security_descriptor)

    # Main read funtion
    # Prints the parsed DACL
    def read(self, principal_security_descriptor):
        parsed_dacl = self.parse_dacl(principal_security_descriptor["Dacl"])
        self.print_parsed_dacl(parsed_dacl)

    # Permits to export the DACL of the targets
    # This function is called before any writing action (write, remove or restore)
    def backup(self, target, target_principal_dn, principal_raw_security_descriptor):
        backup = {}
        backup["sd"] = binascii.hexlify(principal_raw_security_descriptor).decode("latin-1")
        backup["dn"] = str(target_principal_dn)

        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"dacledit-{timestamp}-{target}.bak"
        with open(filename, "w", encoding="latin-1") as outfile:
            json.dump(backup, outfile)
        self.context.log.highlight(f"DACL backed up to {filename}")

    def resolveSID(self, sid):
        """Resolves a SID to its corresponding sAMAccountName."""
        # Tries to resolve the SID from the well known SIDs
        if sid in WELL_KNOWN_SIDS:
            return WELL_KNOWN_SIDS[sid]

        # Tries to resolve the SID from the LDAP domain dump
        try:
            resp = self.connection.search(
                searchFilter=f"(objectSid={sid})",
                attributes=["sAMAccountName"],
            )
            return parse_result_attributes(resp)[0]["sAMAccountName"]
        except Exception:
            self.context.log.debug(f"SID not found in LDAP: {sid}")
            return ""

    # Parses a full DACL
    #   - dacl : the DACL to parse, submitted in a Security Desciptor format
    def parse_dacl(self, dacl):
        parsed_dacl = []
        self.context.log.debug("Parsing DACL")
        for ace in dacl["Data"]:
            parsed_ace = self.parse_ace(ace)
            parsed_dacl.append(parsed_ace)
        return parsed_dacl

    # Parses an access mask to extract the different values from a simple permission
    # https://stackoverflow.com/questions/28029872/retrieving-security-descriptor-and-getting-number-for-filesystemrights
    def parse_perms(self, access_mask):
        perms = [PERM.name for PERM in SIMPLE_PERMISSIONS if (access_mask & PERM.value) == PERM.value]
        # use bitwise NOT operator (~) and sum() function to clear the bits that have been processed
        access_mask &= ~sum(PERM.value for PERM in SIMPLE_PERMISSIONS if (access_mask & PERM.value) == PERM.value)
        perms += [PERM.name for PERM in ACCESS_MASK if access_mask & PERM.value]
        return perms

    # Parses a specified ACE and extract the different values (Flags, Access Mask, Trustee, ObjectType, InheritedObjectType)
    #   - ace : the ACE to parse
    def parse_ace(self, ace):
        # For the moment, only the Allowed and Denied Access ACE are supported
        if ace["TypeName"] in [
            "ACCESS_ALLOWED_ACE",
            "ACCESS_ALLOWED_OBJECT_ACE",
            "ACCESS_DENIED_ACE",
            "ACCESS_DENIED_OBJECT_ACE",
        ]:
            _ace_flags = [FLAG.name for FLAG in ACE_FLAGS if ace.hasFlag(FLAG.value)]
            parsed_ace = {"ACE Type": ace["TypeName"], "ACE flags": ", ".join(_ace_flags) or "None"}

            # For standard ACE
            # Extracts the access mask (by parsing the simple permissions) and the principal's SID
            if ace["TypeName"] in ["ACCESS_ALLOWED_ACE", "ACCESS_DENIED_ACE"]:
                access_mask = f"{', '.join(self.parse_perms(ace['Ace']['Mask']['Mask']))} (0x{ace['Ace']['Mask']['Mask']:x})"
                trustee_sid = f"{self.resolveSID(ace['Ace']['Sid'].formatCanonical()) or 'UNKNOWN'} ({ace['Ace']['Sid'].formatCanonical()})"
                parsed_ace = {
                    "Access mask": access_mask,
                    "Trustee (SID)": trustee_sid
                }
            elif ace["TypeName"] in ["ACCESS_ALLOWED_OBJECT_ACE", "ACCESS_DENIED_OBJECT_ACE"]:  # for object-specific ACE
                # Extracts the mask values. These values will indicate the ObjectType purpose
                access_mask_flags = [FLAG.name for FLAG in ALLOWED_OBJECT_ACE_MASK_FLAGS if ace["Ace"]["Mask"].hasPriv(FLAG.value)]
                parsed_ace["Access mask"] = ", ".join(access_mask_flags)
                # Extracts the ACE flag values and the trusted SID
                object_flags = [FLAG.name for FLAG in OBJECT_ACE_FLAGS if ace["Ace"].hasFlag(FLAG.value)]
                parsed_ace["Flags"] = ", ".join(object_flags) or "None"
                # Extracts the ObjectType GUID values
                if ace["Ace"]["ObjectTypeLen"] != 0:
                    obj_type = bin_to_string(ace["Ace"]["ObjectType"]).lower()
                    try:
                        parsed_ace["Object type (GUID)"] = f"{OBJECT_TYPES_GUID[obj_type]} ({obj_type})"
                    except KeyError:
                        parsed_ace["Object type (GUID)"] = f"UNKNOWN ({obj_type})"
                # Extracts the InheritedObjectType GUID values
                if ace["Ace"]["InheritedObjectTypeLen"] != 0:
                    inh_obj_type = bin_to_string(ace["Ace"]["InheritedObjectType"]).lower()
                    try:
                        parsed_ace["Inherited type (GUID)"] = f"{OBJECT_TYPES_GUID[inh_obj_type]} ({inh_obj_type})"
                    except KeyError:
                        parsed_ace["Inherited type (GUID)"] = f"UNKNOWN ({inh_obj_type})"
                # Extract the Trustee SID (the object that has the right over the DACL bearer)
                parsed_ace["Trustee (SID)"] = f"{self.resolveSID(ace['Ace']['Sid'].formatCanonical()) or 'UNKNOWN'} ({ace['Ace']['Sid'].formatCanonical()})"
        else:  # if the ACE is not an access allowed
            self.context.log.debug(f"ACE Type ({ace['TypeName']}) unsupported for parsing yet, feel free to contribute")
            _ace_flags = [FLAG.name for FLAG in ACE_FLAGS if ace.hasFlag(FLAG.value)]
            parsed_ace = {
                "ACE type": ace["TypeName"],
                "ACE flags": ", ".join(_ace_flags) or "None",
                "DEBUG": "ACE type not supported for parsing by dacleditor.py, feel free to contribute",
            }
        return parsed_ace

    def print_parsed_dacl(self, parsed_dacl):
        """Prints a full DACL by printing each parsed ACE

        parsed_dacl : a parsed DACL from parse_dacl()
        """
        self.context.log.debug("Printing parsed DACL")
        # If a specific right or a specific GUID has been specified, only the ACE with this right will be printed
        # If an ACE type has been specified, only the ACE with this type will be specified
        # If a principal has been specified, only the ACE where he is the trustee will be printed
        for i, parsed_ace in enumerate(parsed_dacl):
            print_ace = True
            self.context.log.debug(f"{parsed_ace=}, {self.rights=}, {self.rights_guid=}, {self.ace_type=}, {self.principal_sid=}")

            # Filter on specific rights
            if self.rights is not None:
                try:
                    if (self.rights == "FullControl") and (self.rights not in parsed_ace["Access mask"]):
                        print_ace = False
                    if (self.rights == "DCSync") and (("Object type (GUID)" not in parsed_ace) or (RIGHTS_GUID.DS_Replication_Get_Changes_All.value not in parsed_ace["Object type (GUID)"])):
                        print_ace = False
                    if (self.rights == "WriteMembers") and (("Object type (GUID)" not in parsed_ace) or (RIGHTS_GUID.WriteMembers.value not in parsed_ace["Object type (GUID)"])):
                        print_ace = False
                    if (self.rights == "ResetPassword") and (("Object type (GUID)" not in parsed_ace) or (RIGHTS_GUID.ResetPassword.value not in parsed_ace["Object type (GUID)"])):
                        print_ace = False
                except Exception as e:
                    self.context.log.debug(f"Error filtering with {parsed_ace=} and {self.rights=}, probably because of ACE type unsupported for parsing yet ({e})")

            # Filter on specific right GUID
            if self.rights_guid is not None:
                try:
                    if ("Object type (GUID)" not in parsed_ace) or (self.rights_guid not in parsed_ace["Object type (GUID)"]):
                        print_ace = False
                except Exception as e:
                    self.context.log.debug(f"Error filtering with {parsed_ace=} and {self.rights_guid=}, probably because of ACE type unsupported for parsing yet ({e})")

            # Filter on ACE type
            if self.ace_type == "allowed":
                try:
                    if ("ACCESS_ALLOWED_OBJECT_ACE" not in parsed_ace["ACE Type"]) and ("ACCESS_ALLOWED_ACE" not in parsed_ace["ACE Type"]):
                        print_ace = False
                except Exception as e:
                    self.context.log.debug(f"Error filtering with {parsed_ace=} and {self.ace_type=}, probably because of ACE type unsupported for parsing yet ({e})")
            else:
                try:
                    if ("ACCESS_DENIED_OBJECT_ACE" not in parsed_ace["ACE Type"]) and ("ACCESS_DENIED_ACE" not in parsed_ace["ACE Type"]):
                        print_ace = False
                except Exception as e:
                    self.context.log.debug(f"Error filtering with {parsed_ace=} and {self.ace_type=}, probably because of ACE type unsupported for parsing yet ({e})")

            # Filter on trusted principal
            if self.principal_sid is not None:
                try:
                    if self.principal_sid not in parsed_ace["Trustee (SID)"]:
                        print_ace = False
                except Exception as e:
                    self.context.log.debug(f"Error filtering with {parsed_ace=} and {self.principal_sid=}, probably because of ACE type unsupported for parsing yet ({e})")
            if print_ace:
                self.context.log.highlight(f"ACE[{i}] info")
                self.print_parsed_ace(parsed_ace)

    # Prints properly a parsed ACE
    #   - parsed_ace : a parsed ACE from parse_ace()
    def print_parsed_ace(self, parsed_ace):
        elements_name = list(parsed_ace.keys())
        for attribute in elements_name:
            self.context.log.highlight(f"\t{attribute:<26}: {parsed_ace[attribute]}")

    # Retrieves the GUIDs for the specified rights
    def build_guids_for_rights(self):
        _rights_guids = []
        if self.rights_guid is not None:
            _rights_guids = [self.rights_guid]
        elif self.rights == "WriteMembers":
            _rights_guids = [RIGHTS_GUID.WriteMembers.value]
        elif self.rights == "ResetPassword":
            _rights_guids = [RIGHTS_GUID.ResetPassword.value]
        elif self.rights == "DCSync":
            _rights_guids = [
                RIGHTS_GUID.DS_Replication_Get_Changes.value,
                RIGHTS_GUID.DS_Replication_Get_Changes_All.value,
            ]
        self.context.log.highlight("Built GUID: %s", _rights_guids)
        return _rights_guids
