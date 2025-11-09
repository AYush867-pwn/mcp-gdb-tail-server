/* ctf_stack_dynamic.c
   Simple GDB CTF: flag stored in two local (stack) variables,
   built dynamically (no contiguous string literal).
   Compile:
     gcc -g -o ctf_stack_dynamic ctf_stack_dynamic.c -no-pie -fno-stack-protector
*/

#include <stdio.h>

void f1(void) {
    /* first part built char-by-char on the stack */
    char key1[12]; /* "FLAG{stack_" + '\0' = 11+1 */
    key1[0] = 'F';
    key1[1] = 'L';
    key1[2] = 'A';
    key1[3] = 'G';
    key1[4] = '{';
    key1[5] = 's';
    key1[6] = 't';
    key1[7] = 'a';
    key1[8] = 'c';
    key1[9] = 'k';
    key1[10] = '_';
    key1[11] = '\0';

    /* do not print key1 — just return so it stays in the stack frame while in this function */
    return;
}

void f2(void) {
    /* second part built char-by-char on the stack */
    char key2[12]; /* "inspection}" + '\0' = 11+1 */
    key2[0] = 'i';
    key2[1] = 'n';
    key2[2] = 's';
    key2[3] = 'p';
    key2[4] = 'e';
    key2[5] = 'c';
    key2[6] = 't';
    key2[7] = 'i';
    key2[8] = 'o';
    key2[9] = 'n';
    key2[10] = '}';
    key2[11] = '\0';

    /* do not print key2 */
    return;
}

int main(void) {
    puts("Quick stack inspection challenge.");
    f1();
    f2();
    puts("Done. Use GDB to inspect the stack frames in f1 and f2 to retrieve the flag.");
    return 0;
}

