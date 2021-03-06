import pickle
import numpy as np
from collections import Counter
from scipy.spatial import cKDTree
from scipy.spatial.distance import minkowski

import env
from base import BaseEstimator
from kernels import get_kernel


class KNNClassifier(BaseEstimator):
    """
    Classifier implementing the (kernelized) k-nearest neighbors vote.

    Parameters
    ----------
    k : positive int, optional
        The number of neighbors to take into account.
    p : float, 1 <= `p` <= infinity, optional
        Which l_p (Minkowski) metric to use.
    weights : {'uniform', 'distance'}, optional
        Weight function used in prediction. Possible values:
        - 'uniform' : uniform weights. All points in each neighborhood are weighted equally.
        - 'distance' : weight points by the inverse of their distance.
          In this case, closer neighbors of a query point will have a greater influence
          than neighbors which are further away.
    algorithm : {'brute', 'kd_tree'}, optional
        Algorithm used to compute the nearest neighbors:
        - 'kd_tree' will use kd-tree
        - 'brute' will use a brute-force search
    leaf_size : positive int, optional
        Leaf size passed to KDTree.
    metric : None or callable, optional
        The distance metric to use. If None, Minkowski metric is used.
        If not None, 'kd-tree' algorithm cannot be used.
    kernel : None, {'rbf', 'poly', 'linear', 'sigmoid'} or callable, optional
        Specifies the kernel type to be used in the algorithm.
        If not None, ignore metric and use kernel as a measure of similarity.
    kernel_params : dict, optional
        Additional kwargs passed to `kernel`.

    Attributes
    ----------
    kd_tree_ : None or scipy.cKDTree
        K-d tree computed on training samples to speed up
        finding nearest neighbors.

    Examples
    --------
    k-NN using brute-force algorithm
    >>> X = [[0., 0.], [0., 1.], [1., 0.], [1., 1.]]
    >>> y = [0, 1, 1, 0]
    >>> X_test = [[0.9, 0.99]]
    >>> knn1 = KNNClassifier(k=3, algorithm='brute').fit(X, y)
    >>> knn1
    KNNClassifier(algorithm='brute', k=3, kd_tree_=None, kernel=None,
           kernel_params={}, leaf_size=30, metric=None, p=2.0,
           weights='uniform')
    >>> knn1.k_neighbors(X_test)
    array([ 3.,  1.,  2.])
    >>> knn1.k_neighbors(X_test, return_distances=True)
    (array([ 3.,  1.,  2.]), array([ 0.10049876,  0.90005555,  0.99503769]))
    >>> knn1.k_neighbors(X_test, k=2, return_distances=True)
    (array([ 3.,  1.]), array([ 0.10049876,  0.90005555]))
    >>> knn1.predict(X_test)
    array([1])
    >>> knn1.set_params(weights='distance').predict(X_test)
    array([0])
    >>> knn1.set_params(metric=lambda x, y: np.abs(x[0] - y[0]) ** 2).predict(X_test)
    array([1])
    >>> knn1.set_params(kernel='rbf').predict(X_test)
    array([0])


    k-NN using brute-force algorithm
    >>> knn2 = KNNClassifier(k=3, algorithm='kd_tree', leaf_size=1).fit(X, y)
    >>> knn2 # doctest: +ELLIPSIS
    KNNClassifier(algorithm='kd_tree', k=3,
           kd_tree_=<scipy.spatial.ckdtree.cKDTree object at 0x...>,
           kernel=None, kernel_params={}, leaf_size=1, metric=None, p=2.0,
           weights='uniform')
    >>> knn2.k_neighbors(X_test)
    array([ 3.,  1.,  2.])
    >>> knn2.predict(X_test)
    array([1])
    >>> knn2.set_params(kernel='poly').predict(X_test)
    Warning: `algorithm`=='kd_tree' cannot be used with custom metric function.
    Switching to `algorithm`=='brute'
    array([1])
    >>> knn2 = knn2.set_params(kernel=None, algorithm='kd_tree')


    Save and load (k-NN) model
    >>> from utils.read_write import load_model

    # this saves state of k-d tree as well, so it won't be constructed again
    >>> knn2.save(filepath='knn.json', json_params=dict(indent=4))

    # `.fit` need to be called attach & validate inputs and
    # this won't build k-d tree again neither!
    >>> knn_loaded = load_model('knn.json').fit(X, y)
    >>> knn_loaded # doctest: +ELLIPSIS
    KNNClassifier(algorithm='kd_tree', k=3,
           kd_tree_=<scipy.spatial.ckdtree.cKDTree object at 0x...>,
           kernel=None, kernel_params={}, leaf_size=1, metric=None, p=2.0,
           weights='uniform')
    >>> knn_loaded.k_neighbors(X_test)
    array([ 3.,  1.,  2.])
    >>> knn_loaded.predict(X_test)
    array([1])


    Set new parameters and reset them
    >>> knn3 = KNNClassifier(k=7).set_params(k=100).set_params(p=2, weights='distance')
    >>> knn3.get_params(False)['k']
    100
    >>> knn3.reset_params().get_params(False)['k']
    7
    """
    def __init__(self, k=5, p=2., weights='uniform', algorithm='kd_tree', leaf_size=30,
                 metric=None, kernel=None, kernel_params={}):

        self.k = k
        self.p = p
        self.weights = weights
        self.algorithm = algorithm
        self.leaf_size = leaf_size
        self.metric = metric
        self.kernel = kernel
        self.kernel_params = kernel_params
        self.kd_tree_ = None
        # TODO: add precompute : bool
        super(KNNClassifier, self).__init__(_y_required=True)

    def _check_metric(self):
        if (self.metric or self.kernel) and self.algorithm == 'kd_tree':
            print ("Warning: `algorithm`=='kd_tree' cannot be used with custom metric function.\n" +
                   "Switching to `algorithm`=='brute'")
            self.algorithm = 'brute'
        if self.kernel:
            if isinstance(self.kernel, str):
                kernel_func = get_kernel(self.kernel, **self.kernel_params)
            else:
                kernel_func = self.kernel
            self._metric = lambda x, y: kernel_func(x, x) - 2. * kernel_func(x, y) \
                                                               + kernel_func(y, y)
        elif self.metric:
            self._metric = self.metric
        else:
            self._metric = lambda x, y: minkowski(x, y, self.p)

    def _fit(self, X, y):
        self._check_metric()
        if self.algorithm == 'kd_tree':
            # this ensures that tree is not built after loading from file
            # if it was already been built
            if self._called_fit or self.kd_tree_ is None:
                self.kd_tree_ = cKDTree(X, leafsize=self.leaf_size)
        elif self.algorithm == 'brute':
            pass
        else:
            raise ValueError("invalid algorithm '{0}'".format(self.algorithm))

    def _k_neighbors_x(self, x, k):
        """
        Find the k nearest neighbors for `x` and
        return their indices along with respective distances.
        """
        if self.algorithm == 'brute':
            # compute distances between x and all examples in the training set.
            distances = [self._metric(x, x_train) for x_train in self._X]
            distances = np.asarray(distances)

            # find k closest points efficiently in O(`n_samples` + k):
            indices = np.argpartition(distances, kth=k - 1)[:k]

            # leave only the respective distances
            distances = distances[indices]

        elif self.algorithm == 'kd_tree':
            distances, indices = self.kd_tree_.query(x, k=k, p=self.p, n_jobs=-2)

        return indices, distances

    def k_neighbors(self, X, k=None, return_distances=False):
        k = k or self.k
        if self._n_samples < k:
            raise ValueError('number of training samples ({0}) must be at least `k`={1}'
                             .format(self._n_samples, k))
        self._check_metric()

        if not isinstance(X, np.ndarray):
            X = np.asarray(X)
        indices, distances = np.array([]), np.array([])
        for x in X:
            indices_x, distances_x = self._k_neighbors_x(x, k)
            indices = np.concatenate((indices, indices_x))
            if return_distances:
                distances = np.concatenate((distances, distances_x))
        return (indices, distances) if return_distances else indices

    def _aggregate(self, neighbors_targets, distances):
        # TODO: split by this method to KNNClassifier, KNNRegressor, ...
        neighbors_targets = np.atleast_1d(neighbors_targets)
        if self.weights == 'uniform':
            return Counter(neighbors_targets).most_common(1)[0][0]
        if self.weights == 'distance':
            return Counter(dict(zip(neighbors_targets, 1./distances))).most_common(1)[0][0]
        raise ValueError("invalid weights '{0}'".format(self.weights))

    def _predict_x(self, x):
        """Predict the target of a single instance x."""
        indices, distances = self._k_neighbors_x(x, self.k)
        return self._aggregate(self._y[indices], distances)

    def _predict(self, X=None):
        # ensure there are at least `k` training samples
        if self._n_samples < self.k:
            raise ValueError('number of training samples ({0}) must be at least `k`={1}'
                             .format(self._n_samples, self.k))
        self._check_metric()
        predictions = [self._predict_x(x) for x in X]
        return np.asarray(predictions)

    def _serialize(self, params):
        if 'kd_tree_' in params:
            kd_tree_ = params['kd_tree_']
            if kd_tree_:
                params['kd_tree_'] = pickle.dumps(kd_tree_)
        return params

    def _deserialize(self, params):
        if 'kd_tree_' in params:
            kd_tree_ = params['kd_tree_']
            if kd_tree_:
                params['kd_tree_'] = pickle.loads(kd_tree_)
        return params


if __name__ == '__main__':
    # run corresponding tests
    from utils.testing import run_tests
    run_tests(__file__)
