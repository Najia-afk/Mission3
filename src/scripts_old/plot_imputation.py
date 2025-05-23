import logging
import numpy as np
import pandas as pd
from dash import Dash, dcc, html
from dash.dependencies import Input, Output, State
import plotly.graph_objs as go
from sklearn.impute import KNNImputer
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.experimental import enable_iterative_imputer  # noqa
from sklearn.impute import IterativeImputer
from sklearn.preprocessing import LabelEncoder

logging.basicConfig(level=logging.INFO)

# Function to run the Dash app
def run_dash_app(df):
    # Encode categorical columns as numbers
    def encode_categorical(df):
        label_encoders = {}
        for col in ['nutrition_grade_fr', 'pnns_groups_1', 'pnns_groups_2']:
            if col in df.columns and df[col].dtype == 'object':
                le = LabelEncoder()
                df[col] = le.fit_transform(df[col].astype(str))
                label_encoders[col] = le
        return df, label_encoders

    # Ensure necessary columns are present
    df, label_encoders = encode_categorical(df)

    # Identify numeric columns (for imputation) and non-numeric columns
    numeric_columns = df.select_dtypes(include=[np.number]).columns.tolist()
    non_numeric_columns = df.select_dtypes(exclude=[np.number]).columns.tolist()

    # Imputation methods
    def impute_data(df, method='median'):
        """Impute missing values based on the selected method."""
        df_imputed = df.copy()

        # Apply imputation only to numeric columns
        if method == 'knn':
            imputer = KNNImputer(n_neighbors=5)
            df_imputed[numeric_columns] = imputer.fit_transform(df[numeric_columns])
        elif method == 'kmeans':
            df_filled = df_imputed[numeric_columns].fillna(df_imputed[numeric_columns].mean())
            kmeans = KMeans(n_clusters=5)
            df_imputed['cluster'] = kmeans.fit_predict(df_filled)
            df_imputed[numeric_columns] = df_imputed.groupby('cluster')[numeric_columns].transform(lambda x: x.fillna(x.mean()))
            df_imputed.drop('cluster', axis=1, inplace=True)
        elif method == 'random_forest':
            for feature in numeric_columns:
                if df_imputed[feature].isnull().any():
                    not_null = df_imputed[df_imputed[feature].notnull()]
                    is_null = df_imputed[df_imputed[feature].isnull()]
                    rf = RandomForestRegressor(n_estimators=100)
                    rf.fit(not_null[numeric_columns].drop(feature, axis=1), not_null[feature])
                    df_imputed.loc[df_imputed[feature].isnull(), feature] = rf.predict(is_null[numeric_columns].drop(feature, axis=1))
        elif method == 'iterative_imputer':
            imputer = IterativeImputer(max_iter=10, random_state=0)
            df_imputed[numeric_columns] = imputer.fit_transform(df[numeric_columns])
        else:
            # Apply median imputation only to numeric columns
            df_imputed[numeric_columns] = df[numeric_columns].fillna(df[numeric_columns].median())
        
        return df_imputed

    # Create and launch Dash app
    app = Dash(__name__)

    def create_layout():
        return html.Div([
            html.H1("Nutrient Clustering Dashboard"),
            
            # Dropdown for selecting imputation method
            html.Label("Select Imputation Method:"),
            dcc.Dropdown(
                id='imputation-method',
                options=[
                    {'label': 'Median/Mean', 'value': 'median'},
                    {'label': 'KNN Imputation', 'value': 'knn'},
                    {'label': 'K-Means Imputation', 'value': 'kmeans'},
                    {'label': 'Random Forest Imputation', 'value': 'random_forest'},
                    {'label': 'Iterative Imputer', 'value': 'iterative_imputer'},
                ],
                value='median',
                placeholder="Select Imputation Method"
            ),
            
            # Dropdown for selecting nutrient columns for clustering
            html.Label("Select Nutrient Columns:"),
            dcc.Dropdown(
                id='nutrient-columns',
                options=[{'label': col, 'value': col} for col in numeric_columns],
                value=['fat_100g', 'sugars_100g'],
                multi=True
            ),
            
            # Input for number of clusters
            html.Label("Select Number of Clusters:"),
            dcc.Input(
                id='num-clusters',
                type='number',
                value=5,
                min=2,
                max=10,
                step=1
            ),
            
            # Checkbox for 3D Visualization
            html.Label("3D Visualization (includes Nutriscore):"),
            dcc.Checklist(
                id='3d-visualization',
                options=[{'label': 'Enable 3D Plot', 'value': '3d'}],
                value=[]
            ),
            
            # Button to trigger the clustering and visualization
            html.Button("Apply Imputation and Cluster", id='apply-imputation', n_clicks=0),
            
            # Graph to show clusters
            dcc.Graph(id='cluster-graph')
        ])

    app.layout = create_layout()

    @app.callback(
        Output('cluster-graph', 'figure'),
        Input('apply-imputation', 'n_clicks'),
        State('imputation-method', 'value'),
        State('nutrient-columns', 'value'),
        State('num-clusters', 'value'),
        State('3d-visualization', 'value')
    )
    def update_clusters(n_clicks, method, nutrients, num_clusters, is_3d):
        if n_clicks > 0:
            # Impute the missing values (numeric columns only)
            df_imputed = impute_data(df, method)

            # Perform clustering based on selected nutrient columns
            kmeans = KMeans(n_clusters=num_clusters)
            df_imputed['cluster'] = kmeans.fit_predict(df_imputed[nutrients].fillna(0))

            # Train a model to predict PNNS categories
            df_train = df_imputed[df_imputed['pnns_groups_1'].notnull()]
            X_train = df_train[nutrients]
            y_train = df_train['pnns_groups_1']
            model = RandomForestClassifier()
            model.fit(X_train, y_train)

            # Predict PNNS categories for all data
            df_imputed['predicted_pnns'] = model.predict(df_imputed[nutrients])

            # Visualization
            color_mapping = {category: idx for idx, category in enumerate(df_imputed['predicted_pnns'].unique())}
            colors = df_imputed['predicted_pnns'].map(color_mapping)

            if '3d' in is_3d and 'nutrition-score-fr_100g' in df_imputed.columns:
                fig = go.Figure(data=[go.Scatter3d(
                    x=df_imputed[nutrients[0]], y=df_imputed[nutrients[1]], z=df_imputed['nutrition-score-fr_100g'],
                    mode='markers', marker=dict(size=5, color=colors, colorscale='Viridis', opacity=0.8),
                    text=df_imputed['predicted_pnns']
                )])
                fig.update_layout(scene=dict(
                    xaxis_title=nutrients[0], yaxis_title=nutrients[1], zaxis_title='Nutrition Score FR'
                ), title="3D Nutrient Clusters with Predicted PNNS Categories")
            else:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_imputed[nutrients[0]], y=df_imputed[nutrients[1]], mode='markers',
                    marker=dict(size=10, color=colors, colorscale='Viridis', showscale=True),
                    text=df_imputed['predicted_pnns']
                ))
                fig.update_layout(
                    title="Nutrient Clusters with Predicted PNNS Categories",
                    xaxis_title=nutrients[0],
                    yaxis_title=nutrients[1]
                )
            return fig
        return {}

    app.run_server(debug=True)
