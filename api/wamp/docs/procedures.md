# Procedures

Unless explicitly noted **all** procedures implicitly have the `guild id` 
(snowflake) as their first argument.

Additionally, multi-user connections must pass the `user id` (snowflake) on 
whose behalf the procedure is to be run as the second argument.

> To learn more about multi-user connections, see [Authentication](authentication.md).

## Player

Prefixed with "player.".

### enqueue
### dequeue

### move
### skip_next
### skip_prev

### pause
### seek
### volume

## RBAC

Prefixed with "rbac."

### get_role
Get a role by its name or id.
    
### get_roles
Get the roles for a target.

Arguments:
- target (string): Target to get roles for

### assign_role
Add a role to a target.

Arguments:
- role (snowflake): ID of the role
- target (string): Target to add role to

### unassign_role
Remove a role from a target.

Arguments:
- role (snowflake): ID of the role
- target (string): Target to remove roles from

### create_role
Create a new role.

### delete_role
Delete a role.

Arguments:
- role (snowflake): ID of the role to delete