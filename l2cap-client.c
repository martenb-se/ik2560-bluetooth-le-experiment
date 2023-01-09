/**
 * Code is modified from:
 * https://people.csail.mit.edu/albert/bluez-intro/x559.html#l2cap-client.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <bluetooth/bluetooth.h>
#include <bluetooth/l2cap.h>
#include <pthread.h>

int FLAG_QUIT = 0;
pthread_mutex_t flag_quit_lock;
pthread_t thread_receiver_id, thread_sender_id;

/**
 * Get status of global quit flag.
 * @return THe status of the quit flag.
 */
int get_flag_quit() {
    int result = 0;
    pthread_mutex_lock(&flag_quit_lock);
    result = FLAG_QUIT == 1;
    pthread_mutex_unlock(&flag_quit_lock);
    return result;
}

/**
 * Set status of global quit flag.
 */
int set_flag_quit(int status) {
    pthread_mutex_lock(&flag_quit_lock);
    FLAG_QUIT = status;
    pthread_mutex_unlock(&flag_quit_lock);
}

/**
 * Thread to receive messages from the server.
 *
 * @param th_args The thread argument.
 * @return Nothing
 */
void *thread_receiver(void *th_args) {
    long bytes_read;
    char receive_msg_buf[673] = {0};
    int *s = (int *)th_args;
    int quit = 0;

    while(!quit) {
        if (get_flag_quit())
            break;

        memset(receive_msg_buf, 0, sizeof(receive_msg_buf));
        bytes_read = read(*s, receive_msg_buf, sizeof(receive_msg_buf));

        quit = strcmp(receive_msg_buf, "bye") == 0;

        if( bytes_read > 0 )
            printf("Server: %s\n", receive_msg_buf);
        else
            quit = 1;

        if (quit) {
            set_flag_quit(1);
            pthread_cancel(thread_sender_id);
        }

    }

    pthread_exit(NULL);
}

/**
 * Thread to send messages to the server.
 *
 * @param th_args The thread argument.
 * @return Nothing
 */
void *thread_sender(void *th_args) {
    long status;
    int max_send = 672, quit = 0;
    char send_msg[673] = {0};
    int *s = (int *)th_args;

    while(quit != 1) {
        if (get_flag_quit())
            break;

        memset(send_msg, 0, sizeof(send_msg));
        fgets(send_msg, max_send, stdin);

        // Remove trailing newlines
        send_msg[strcspn(send_msg, "\n\r")] = 0;

        status = write(*s, send_msg, strlen(send_msg));

        if (status < 0) {
            perror("Error sending message");
            quit = 1;
        }

        quit = strcmp(send_msg, "bye") == 0;

        // Set global quit
        if (quit) {
            set_flag_quit(1);
            pthread_cancel(thread_receiver_id);
        }

    }

    pthread_exit(NULL);
}

int main(int argc, char **argv)
{
    struct sockaddr_l2 addr = { 0 };
    int s;
    long status;
    char dest[18] = "01:23:45:67:89:AB";

    if(argc < 2)
    {
        fprintf(stderr, "usage: %s <bt_addr>\n", argv[0]);
        exit(2);
    }

    strncpy(dest, argv[1], 18);

    // allocate a socket
    s = socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP);

    // set the connection parameters (who to connect to)
    addr.l2_family = AF_BLUETOOTH;
    addr.l2_psm = htobs(0x1001);
    str2ba( dest, &addr.l2_bdaddr );

    // connect to server
    status = connect(s, (struct sockaddr *)&addr, sizeof(addr));

    if (status == 0) {
        printf("Connected to %s, begin sending messages below.\n", dest);

        // Start threads to send and receive data
        pthread_create(&thread_receiver_id, NULL, thread_receiver, (void *)&s);
        pthread_create(&thread_sender_id, NULL, thread_sender, (void *)&s);

        // Wait for threads to finish
        pthread_join(thread_receiver_id, NULL);
        pthread_join(thread_sender_id, NULL);
    }

    close(s);
}