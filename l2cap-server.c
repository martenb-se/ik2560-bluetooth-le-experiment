/**
 * Code is modified from:
 * https://people.csail.mit.edu/albert/bluez-intro/x559.html#l2cap-server.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <bluetooth/bluetooth.h>
#include <bluetooth/l2cap.h>
#include <bluetooth/hci.h>
#include <bluetooth/hci_lib.h>
#include <sys/ioctl.h>
#include <pthread.h>

int FLAG_QUIT = 0;
pthread_mutex_t flag_quit_lock;
pthread_t thread_receiver_id, thread_sender_id;

/**
 * From https://github.com/pauloborges/bluez/blob/master/tools/hcitool.c#L77
 * Display addresses for the Bluetooth adapters on the device.
 */
static int dev_info(int s, int dev_id, long arg)
{
    struct hci_dev_info di = { .dev_id = dev_id };
    char addr[18];

    if (ioctl(s, HCIGETDEVINFO, (void *) &di))
    return 0;

    ba2str(&di.bdaddr, addr);
    printf("\t%s\t%s\n", di.name, addr);
    return 0;
}

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
 * Thread to receive messages from the client.
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
            printf("Client: %s\n", receive_msg_buf);
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
 * Thread to send messages to the client.
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
    struct sockaddr_l2 loc_addr = { 0 }, rem_addr = { 0 };
    char buf[1024] = { 0 };
    int s, client;
    long status;
    socklen_t opt = sizeof(rem_addr);

    printf("Devices:\n");
    hci_for_each_dev(HCI_UP, dev_info, 0);

    // allocate socket
    s = socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP);

    // bind socket to port 0x1001 of the first available
    // bluetooth adapter
    loc_addr.l2_family = AF_BLUETOOTH;
    loc_addr.l2_bdaddr = *BDADDR_ANY;
    loc_addr.l2_psm = htobs(0x1001);

    status = bind(s, (struct sockaddr *)&loc_addr, sizeof(loc_addr));

    if(status != 0 ) {
        fprintf(stderr, "bind failed\n");
        exit(2);
    }

    // put socket into listening mode
    listen(s, 1);

    // accept one connection
    client = accept(s, (struct sockaddr *)&rem_addr, &opt);

    ba2str( &rem_addr.l2_bdaddr, buf );
    fprintf(stderr, "accepted connection from %s\n", buf);
    printf("Begin sending messages below.\n");

    // Start threads to send and receive data
    pthread_create(&thread_receiver_id, NULL, thread_receiver, (void *)&client);
    pthread_create(&thread_sender_id, NULL, thread_sender, (void *)&client);

    // Wait for threads to finish
    pthread_join(thread_receiver_id, NULL);
    pthread_join(thread_sender_id, NULL);

    // close connection
    close(client);
    close(s);
}
