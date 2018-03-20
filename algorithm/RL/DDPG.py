# coding=utf-8

import tensorflow as tf
import numpy as np

import logging

from algorithm import config
from base.env.finance import StockEnv
from helper.args_parser import model_launcher_parser


class Algorithm(object):

    def __init__(self, session, a_space, s_space, **options):

        # Initialize session.
        self.session = session

        # Initialize evn parameters.
        self.a_space, self.s_space = a_space, s_space

        self.actor_loss, self.critic_loss = .0, .0

        try:
            self.learning_rate = options['learning_rate']
        except KeyError:
            self.learning_rate = 0.001

        try:
            self.gamma = options['gamma']
        except KeyError:
            self.gamma = 0.9

        try:
            self.tau = options['tau']
        except KeyError:
            self.tau = 0.01

        try:
            self.batch_size = options['batch_size']
        except KeyError:
            self.batch_size = 32

        try:
            self.buffer_size = options['buffer_size']
        except KeyError:
            self.buffer_size = 10000

        # Initialize buffer.
        self.buffer = np.zeros((self.buffer_size, self.s_space * 2 + self.a_space + 1))
        self.buffer_length = 0

        self._init_input()
        self._init_nn()
        self._init_op()

    def _init_input(self):
        self.s = tf.placeholder(tf.float32, [None, self.s_space], 'state')
        self.r = tf.placeholder(tf.float32, [None, 1], 'reward')
        self.s_next = tf.placeholder(tf.float32, [None, self.s_space], 'state_next')

    def _init_nn(self):
        # Initialize predict actor and critic.
        self.a_predict = self.__build_actor_nn(self.s, "predict/actor", trainable=True)
        self.q_predict = self.__build_critic(self.s, self.a_predict, "predict/critic", trainable=True)
        # Initialize target actor and critic.
        self.a_next = self.__build_actor_nn(self.s_next, "target/actor", trainable=False)
        self.q_next = self.__build_critic(self.s_next, self.a_next, "target/critic", trainable=False)
        # Save scopes
        self.scopes = ["predict/actor", "target/actor", "predict/critic", "target/critic"]

    def _init_op(self):
        # Get actor and critic parameters.
        params = [tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, scope) for scope in self.scopes]
        zipped_a_params, zipped_c_params = zip(params[0], params[1]), zip(params[2], params[3])
        # Initialize update actor and critic op.
        self.update_a = [tf.assign(t_a, (1 - self.tau) * t_a + self.tau * p_a) for p_a, t_a in zipped_a_params]
        self.update_c = [tf.assign(t_c, (1 - self.tau) * t_c + self.tau * p_c) for p_c, t_c in zipped_c_params]
        # Initialize actor loss and train op.
        self.a_loss = -tf.reduce_mean(self.q_predict)
        self.a_train_op = tf.train.RMSPropOptimizer(self.learning_rate).minimize(self.a_loss, var_list=params[0])
        # Initialize critic loss and train op.
        self.q_target = self.r + self.gamma * self.q_next
        self.c_loss = tf.losses.mean_squared_error(self.q_target, self.q_predict)
        self.c_train_op = tf.train.RMSPropOptimizer(self.learning_rate * 2).minimize(self.c_loss, var_list=params[2])
        # Initialize variables.
        self.session.run(tf.global_variables_initializer())

    def train(self):
        if self.buffer_length < self.buffer_size:
            return
        self.session.run([self.update_a, self.update_c])
        s, a, r, s_next = self.get_transition_batch()
        self.critic_loss, _ = self.session.run([self.c_loss, self.c_train_op], {self.s: s, self.a_predict: a, self.r: r, self.s_next: s_next})
        self.actor_loss, _ = self.session.run([self.a_loss, self.a_train_op], {self.s: s})

    def predict_action(self, s):
        a = self.session.run(self.a_predict, {self.s: s})
        return a

    def get_transition_batch(self):
        indices = np.random.choice(self.buffer_size, size=self.batch_size)
        batch = self.buffer[indices, :]
        s = batch[:, :self.s_space]
        a = batch[:, self.s_space: self.s_space + self.a_space]
        r = batch[:, -self.s_space - 1: -self.s_space]
        s_next = batch[:, -self.s_space:]
        return s, a, r, s_next

    def save_transition(self, s, a, r, s_next):
        transition = np.hstack((s, a, [[r]], s_next))
        self.buffer[self.buffer_length % self.buffer_size, :] = transition
        self.buffer_length += 1

    def log_loss(self, episode):
        logging.warning("Episode: {0} | Actor Loss: {1:.2f} | Critic Loss: {2:.2f}".format(episode,
                                                                                           self.actor_loss,
                                                                                           self.critic_loss))

    def __build_actor_nn(self, state, scope, trainable=True):

        w_init, b_init = tf.random_normal_initializer(.0, .3), tf.constant_initializer(.1)

        with tf.variable_scope(scope):
            # state is ? * code_count * data_dim.
            first_dense = tf.layers.dense(state,
                                          32,
                                          tf.nn.relu,
                                          kernel_initializer=w_init,
                                          bias_initializer=b_init,
                                          trainable=trainable)

            second_dense = tf.layers.dense(first_dense,
                                           32,
                                           tf.nn.relu,
                                           kernel_initializer=w_init,
                                           bias_initializer=b_init,
                                           trainable=trainable)

            action_prob = tf.layers.dense(second_dense,
                                          self.a_space,
                                          tf.nn.tanh,
                                          kernel_initializer=w_init,
                                          bias_initializer=b_init,
                                          trainable=trainable)

            # But why?
            return action_prob

    @staticmethod
    def __build_critic(state, action, scope, trainable=True):

        w_init, b_init = tf.random_normal_initializer(.0, .3), tf.constant_initializer(.1)

        with tf.variable_scope(scope):

            s_first_dense = tf.layers.dense(state,
                                            32,
                                            tf.nn.relu,
                                            kernel_initializer=w_init,
                                            bias_initializer=b_init,
                                            trainable=trainable)

            s_second_dense = tf.layers.dense(s_first_dense,
                                             32,
                                             tf.nn.relu,
                                             kernel_initializer=w_init,
                                             bias_initializer=b_init,
                                             trainable=trainable)

            a_first_dense = tf.layers.dense(action,
                                            32,
                                            kernel_initializer=w_init,
                                            bias_initializer=b_init,
                                            trainable=trainable)

            a_second_dense = tf.layers.dense(a_first_dense,
                                             32,
                                             kernel_initializer=w_init,
                                             bias_initializer=b_init,
                                             trainable=trainable)

            q_value = tf.layers.dense(tf.nn.relu(s_second_dense + a_second_dense),
                                      1,
                                      kernel_initializer=w_init,
                                      bias_initializer=b_init,
                                      trainable=trainable)

            return q_value


if __name__ == '__main__':
    args = model_launcher_parser.parse_args()
    env = StockEnv(args.codes, **{
        "session": tf.Session(config=config),
        "agent_class": Algorithm,
        "log_level": args.log_level
    })
    env.run()


