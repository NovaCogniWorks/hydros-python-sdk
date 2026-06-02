import pandas as pd
import numpy as np
from scipy.spatial import Delaunay
from scipy.interpolate import LinearNDInterpolator
from scipy.optimize import minimize_scalar
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression

class PumpUnit:
    def __init__(self, name, df_e, df_r):
        self.name = name
        self.data_e = df_e
        self.data_r = df_r
        
        # Fitting and interpolation
        self.poly = PolynomialFeatures(degree=2, include_bias=False)
        self.model_e = LinearRegression()
        self._fit_efficiency()
        
        self.interp_r = None
        self._build_interpolation()
        
        # Boundaries and geometry
        self.hull = None
        self.q_min = df_e['Q'].min()
        self.q_max = df_e['Q'].max()
        self.h_min = df_e['H'].min()
        self.h_max = df_e['H'].max()
        self._build_boundary()

    def _fit_efficiency(self):
        X = self.data_e[['Q', 'H']].values
        y = self.data_e['E'].values
        self.model_e.fit(self.poly.fit_transform(X), y)

    def _build_interpolation(self):
        points = self.data_r[['Q', 'H']].values
        # The angle column might be 'R', 'Alpha', or something else, but it's the one that is not Q and not H
        angle_col = [c for c in self.data_r.columns if c not in ['Q', 'H']][0]
        values = self.data_r[angle_col].values 
        self.angle_min = float(np.nanmin(values))
        self.angle_max = float(np.nanmax(values))
        self.interp_r = LinearNDInterpolator(points, values)

    def _build_boundary(self):
        points = self.data_e[['Q', 'H']].values
        if len(points) > 3:
            self.hull = Delaunay(points)

    def predict_efficiency(self, Q, H):
        return self.model_e.predict(self.poly.transform([[Q, H]]))[0]
    
    def predict_opening(self, Q, H):
        val = self.interp_r(Q, H)
        return float(val) if not np.isnan(val) else np.nan

    def predict_flow(self, target_angle, H):
        if target_angle == "-":
            return 0.0
        target_angle = float(target_angle)
        def obj(q):
            pred_angle = self.predict_opening(q, H)
            if np.isnan(pred_angle):
                return 1e6
            return (pred_angle - target_angle)**2
        res = minimize_scalar(obj, bounds=(self.q_min, self.q_max), method='bounded')
        if res.success and res.fun < 1e5:
            return res.x
        return 0.0

    def is_feasible(self, Q, H):
        if not (self.q_min <= Q <= self.q_max and self.h_min <= H <= self.h_max):
            return False
        if self.hull:
            return self.hull.find_simplex([Q, H]) >= 0
        return True
